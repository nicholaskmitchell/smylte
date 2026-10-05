"""The mail pipeline: from a mailbox to suggestions the owner approves or rejects.

`Ingestor.run_once` is one scan. It opens the mailbox, walks the configured
folders from a per-folder cursor, and hands each new message to
`process_message`, which decides in ten stages what — if anything — the
message should become:

 1. ledger      — claim the message's key; a message is processed once, ever,
                  whichever folder it turns up in and however often it is seen
 2. folder      — never read Sent, Drafts, All Mail, Spam, Trash
 3. self        — the owner's own mail is skipped, notes to self are kept
 4. never_parse — the owner's block list
 5. always_parse— the owner's allow list, honoured only for authenticated mail
 6. bulk        — newsletters and robots (List-Unsubscribe, Precedence, ...)
 7. fast path   — an attached invite becomes an event without the model
 8. extract     — the model reads what is left of the body
 9. dedup       — same thread, an open task, a pending or a dismissed suggestion
10. stage       — write the suggestion

Every message ends in exactly one ledger row saying which stage decided and
why, so the owner can see why a mail did or did not become a suggestion.

Why it is built this way:

- **Claim before work, settle after.** The ledger row is written before the
  model is called, so two overlapping scans (the timer and "Scan now") cannot
  both stage the same message; the slow work happens outside the service lock
  and the result is written in one transaction. A transient failure (Anthropic
  rate-limited or down) releases the claim instead of settling it, and the
  folder stops there so the cursor does not move past a message that was never
  read. The alternative — settle every failure — silently loses mail on every
  Anthropic outage.
- **An interrupted run loses nothing, three times.** A run starts by
  releasing every claim nobody settled: the run lock makes this process the
  only claimer, so such a claim belongs to a run that died (crash, kill,
  restart), and its message is read again. Each such death is a strike, and
  at the third the message is settled as an error: one that kills or hangs
  the process would otherwise be read first on every start, looping the
  service and stopping its folder for good. A claim found held mid-run is
  retried later, never called a duplicate. Shutdown asks the scan to stop after the message in hand and
  waits for it, so the cursor is saved before the database closes. A message
  that cannot even be parsed is settled as an error under a hash of its
  bytes: one message never stops a folder or a run.
- **A date window ends at UIDNEXT.** The first scan of a folder (and a rescan
  after the server renumbered it) searches by date. Once that window is done
  the cursor jumps to the folder's UIDNEXT, so an old message sitting at a
  high UID is not read on the next run; a window cut short (too many
  messages, a stop) is remembered and continued, by date, next time.
- **A dropped connection is retried once.** A network or protocol failure on
  a folder saves the cursor, reconnects once and retries the folder; a
  second failure ends the run with the error.
- **Configuration errors stop the run.** A missing or rejected key, an unknown
  model: every further message would fail the same way, and settling each one
  as an error would burn through the inbox. `RunAbort` releases the message in
  hand and ends the run; the next run, after the owner fixes the setting,
  starts where this one stopped.
- **The allow list needs authentication.** `always_parse` lets a school's
  `noreply@` portal past the bulk filter — but only when a trusted server
  (Proton's inbound MTA) wrote that the From domain passed DMARC, SPF or DKIM.
  Otherwise anybody could put that address in a From header and skip the
  filter; the message is then treated as ordinary mail, not dropped.
- **Cheap checks first.** Everything before stage 8 is local and
  deterministic, and most mail ends there: the model is called only for
  person-to-person mail that is not obviously bulk.
- **Dedup asks only when there is something to compare with.** Open tasks
  are retrieved by full-text search on the extraction's words, pending
  suggestions by word overlap; only when either turns up a candidate is
  "new", "duplicate" or "update" decided — by TypeSafe's Jev, with Claude
  deciding whenever Jev is unsure or unreachable, or by Claude alone, as
  Settings says. Measured on labelled mail (`dev/mail_eval/README.md`), Jev
  this way never merged new work into an existing task where Claude alone
  did; a merge is a request the owner never sees. A possible duplicate the
  owner can reject beats a lost task, so every unclear answer means "new".
- **Task or event** is decided after extraction, by the model, the owner's
  rules (`kindrules`) or Jev, as Settings says. Jev failing never stops the
  pipeline: the extraction model's choice stands and the ledger says so.
- **Jev needs a key to be asked at all.** "jev" is the default for both
  decisions, but without a TypeSafe key the model decides, silently: the
  key's presence is the owner's opt-in to sending email text to TypeSafe,
  and an unset key is not news worth a ledger note on every message.

Nothing here logs a subject or a body: logs carry folder names, UIDs, ledger
keys, stages and outcomes, and every error string passes through `redact`.
"""
from __future__ import annotations

import email
import hashlib
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..db import store
from . import addresses, authres, fastpaths, imap, kindrules, message, review, settings
from .imap import FolderInfo, ImapConfig, MailConnectError
from .jev import CHANGED_T as JEV_CHANGED_T
from .jev import MIN_CONFIDENCE as JEV_MIN_CONFIDENCE
from .jev import JevClient, JevError
from .llm import Candidate, EmailForExtraction, Extraction, LlmClient, LlmError, Match
from .message import ParsedMessage
from .redact import redact, redact_exc
from .secrets import SecretStoreError
from .settings import MAIL_SETTINGS_KEY, MAIL_STATUS_KEY, MailConfig

log = logging.getLogger("smylted.mail")

MAX_PER_FOLDER_PER_RUN = 100
# Runs that may die holding one message before it is given up (see the module
# docstring): enough to ride out a restart or two, few enough to stop a loop.
MAX_INTERRUPTED = 3
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
# Long enough for any approval's CalDAV write to finish (its timeout is 30 s).
STUCK_APPROVING_AGE = timedelta(minutes=10)
# Quote stripping runs before the body is cut to `body_max_chars`; this bounds
# its input so a megabyte of text costs no more than the body anyone reads.
MAX_STRIP_CHARS = 200_000
AUTHRES_SAMPLE = 10
MAX_CANDIDATE_TASKS = 5
MAX_CANDIDATE_SUGGESTIONS = 5
MAX_CANDIDATE_REJECTIONS = 5
MAX_FASTPATH_EVENTS = 5
MAX_DETAIL_CHARS = 500

_BULK_PRECEDENCE = frozenset({"bulk", "list", "junk"})
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "your", "you", "this", "that", "from", "please",
    "bitte", "und", "der", "die", "das", "mit", "für", "von",
})
_NON_ALNUM = re.compile(r"[\W_]+")            # anything but letters and digits, any script
_SPECIAL_USE = {
    "\\all": "\\All", "\\archive": "\\Archive", "\\drafts": "\\Drafts", "\\flagged": "\\Flagged",
    "\\important": "\\Important", "\\junk": "\\Junk", "\\sent": "\\Sent", "\\trash": "\\Trash",
}


@dataclass
class Outcome:
    stage: str           # ledger|folder|self|never|always|bulk|fastpath|extract|dedup|stage|error
    outcome: str         # duplicate|skipped|not_actionable|staged|attached|suppressed|error|retry
    detail: str = ""
    suggestion_id: str | None = None
    transient: bool = False


class RunAbort(Exception):
    """A configuration problem that makes every further message pointless (no key, key rejected,
    model unknown). Stops the run; the message in hand is released for the next run."""


@dataclass
class RunReport:
    started_at: str
    finished_at: str | None = None
    ok: bool = True
    skipped_reason: str | None = None     # "disabled" | "deployment" | "busy" | "stopping"
    error: str | None = None
    reconnects: int = 0
    counts: dict[str, int] = field(default_factory=dict)      # outcome -> n
    folders: dict[str, dict] = field(default_factory=dict)    # folder -> {"uidvalidity","fetched","last_uid","rescanned"}


@dataclass
class _Msg:
    """One claimed message and what the stages have learned about it."""
    folder: FolderInfo
    msg: ParsedMessage
    key: str
    tid: str
    internaldate: datetime | None
    cfg: MailConfig
    extra: list[str] = field(default_factory=list)   # reasons appended to the final ledger detail

    @property
    def sent(self) -> datetime | None:
        return self.msg.date or self.internaldate


# ── small helpers ──

def _iso(dt: datetime) -> str:
    """`dt` in the stamp format the database writes (see `settings.utcnow_iso`)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _token_list(text: str | None) -> list[str]:
    """Casefolded words of three letters or more, stopwords removed, in order, once."""
    out: list[str] = []
    for t in _NON_ALNUM.split((text or "").casefold()):
        if len(t) >= 3 and t not in _STOPWORDS and t not in out:
            out.append(t)
    return out


def _tokens(text: str | None) -> set[str]:
    return set(_token_list(text))


def _terms(ex: Extraction) -> list[str]:
    """Search words for open tasks like `ex`: the title's, then the notes'."""
    out = _token_list(ex.title)
    for t in _token_list(ex.notes)[:20]:
        if t not in out:
            out.append(t)
    return out[:12]


def _overlap(a: str | None, b: str | None) -> float:
    """Jaccard similarity of the two texts' words."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _collapsed(text: str | None) -> str:
    return _NON_ALNUM.sub("", (text or "").casefold())


def _same_item(ex: Extraction, r) -> bool:
    """Is `ex` what the owner already dismissed as rejection `r`?

    Same words in any order (or the same letters once punctuation is gone),
    and the same due date unless this extraction has none. A changed deadline
    is new information, so it is allowed through to the dedup question.
    """
    ta, tb = _tokens(ex.title), _tokens(r["title"])
    same = bool(ta) and " ".join(sorted(ta)) == " ".join(sorted(tb))
    if not same:
        ca = _collapsed(ex.title)
        same = bool(ca) and ca == _collapsed(r["title"])
    return same and (ex.due is None or ex.due.isoformat() == r["due"])


def _detail(base: str, extra: list[str] | tuple[str, ...] = ()) -> str:
    text = "; ".join(p for p in (base, *extra) if p)
    return redact(text)[:MAX_DETAIL_CHARS]


def _load_updates(raw: Any) -> list:
    if isinstance(raw, list):
        return list(raw)
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _all_day(start: date | datetime) -> bool:
    return isinstance(start, date) and not isinstance(start, datetime)


class Ingestor:
    """One mailbox reader for one service. Thread-safe for `run_once` (a second
    concurrent call returns a "busy" report); `process_message` may also be
    called directly, which the API tests and the CLI do."""

    def __init__(self, host, secret_store, *, llm=None, jev=None, source_factory=None,
                 deployment_enabled: bool = True, clock=None, log=None):
        self._host = host
        self._secrets = secret_store
        self._llm = llm if llm is not None else LlmClient(
            api_key_provider=lambda: self._secrets.get("anthropic_api_key"),
            # Read from Settings on every call, so a changed model or workspace
            # applies to the next email without a restart.
            model_provider=lambda: self.config().model,
            workspace_provider=lambda: self.config().anthropic_workspace_id or None,
        )
        self._jev = jev if jev is not None else JevClient(
            api_key_provider=lambda: self._secrets.get("typesafe_api_key"),
            model_provider=lambda: self.config().jev_model,
        )
        self._source_factory: Callable[..., Any] = source_factory or imap.connect
        self._deployment_enabled = deployment_enabled
        self._clock: Callable[[], datetime] = clock or (lambda: datetime.now(timezone.utc))
        self._log = log or logging.getLogger("smylted.mail")
        self._run_lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def llm(self) -> LlmClient:
        return self._llm

    @property
    def jev(self) -> JevClient:
        return self._jev

    def config(self) -> MailConfig:
        return settings.load(self._host.mail(store.get_meta_json, MAIL_SETTINGS_KEY))

    def poll_interval_s(self) -> float:
        cfg = self.config()
        if cfg.enabled and self._deployment_enabled:
            return float(cfg.poll_minutes * 60)
        return 300.0

    # ── one scan ──

    def request_stop(self) -> None:
        """Ask a running scan to stop after the message in hand, and refuse new ones.
        For shutdown; there is no way back."""
        self._stop.set()

    def wait_idle(self, timeout: float) -> bool:
        """Wait up to `timeout` seconds for a running scan to finish; True when none runs."""
        if not self._run_lock.acquire(timeout=timeout):
            return False
        self._run_lock.release()
        return True

    def run_once(self) -> RunReport:
        """Scan every configured folder once. Never raises."""
        if self._stop.is_set():
            now = settings.utcnow_iso()
            return RunReport(started_at=now, finished_at=now, skipped_reason="stopping")
        if not self._run_lock.acquire(blocking=False):
            now = settings.utcnow_iso()
            return RunReport(started_at=now, finished_at=now, skipped_reason="busy")
        try:
            return self._run_locked()
        finally:
            self._run_lock.release()

    def _run_locked(self) -> RunReport:
        report = RunReport(started_at=settings.utcnow_iso())
        try:
            cfg = self.config()
            # Skipped runs leave the stored status alone: "switched off" is not
            # news, and it must not wipe the last error the owner has not read.
            if not self._deployment_enabled:
                report.skipped_reason = "deployment"
            elif not cfg.enabled:
                report.skipped_reason = "disabled"
            if report.skipped_reason:
                report.finished_at = settings.utcnow_iso()
                return report
            self._scan(cfg, report)
        except Exception as exc:  # noqa: BLE001 — the loop must survive anything
            report.ok = False
            report.error = redact_exc(exc)
            self._log.warning("mail: run failed: %s", report.error)
        report.finished_at = settings.utcnow_iso()
        self._write_status(report)
        return report

    def _fail(self, report: RunReport, error: str) -> None:
        report.ok = False
        report.error = redact(error)
        self._log.warning("mail: run stopped: %s", report.error)

    @staticmethod
    def _check_binding(cfg: MailConfig) -> None:
        """Refuse a stored password saved for other server settings (see
        `settings.password_binding_ok`): sending it to whatever host the
        settings now name would hand the Bridge password to that host."""
        if not settings.password_binding_ok(cfg):
            raise MailConnectError(settings.PASSWORD_BINDING_MESSAGE, kind="config")

    def _imap_config(self, cfg: MailConfig) -> ImapConfig:
        return ImapConfig(host=cfg.imap_host, port=cfg.imap_port, username=cfg.imap_username,
                          tls=cfg.imap_tls, cert_mode=cfg.imap_cert_mode,
                          pinned_cert_pem=cfg.imap_pinned_cert)

    def _scan(self, cfg: MailConfig, report: RunReport) -> None:
        now = self._clock()
        # The run lock makes this process the only claimer, so an unsettled
        # claim at the start of a run belongs to a run that never finished —
        # crash, kill, restart — and its message must be read again, unless it
        # has now done that MAX_INTERRUPTED times.
        _released, gave_up = self._host.mail(store.mail_recover_unsettled,
                                             max_interrupted=MAX_INTERRUPTED)
        if gave_up:
            self._log.warning("mail: gave up on %d message(s) that interrupted %d scans",
                              gave_up, MAX_INTERRUPTED)
        # An approve interrupted after its compare-and-swap; the deterministic
        # client_id makes the retried create idempotent.
        self._host.mail(store.mail_reset_stuck_approving,
                        before=_iso(now - STUCK_APPROVING_AGE))
        try:
            password = self._secrets.get("imap_password")
            api_key = self._secrets.get("anthropic_api_key")
        except SecretStoreError as e:
            return self._fail(report, str(e))
        if not password:
            return self._fail(report, "no IMAP password is set")
        if not api_key:
            # Checked here rather than at the first extraction: without a key
            # every message would be claimed and released for nothing.
            return self._fail(report, "no Anthropic API key is set")
        try:
            self._check_binding(cfg)
            source = self._source_factory(self._imap_config(cfg), password)
        except MailConnectError as e:
            return self._fail(report, str(e))
        try:
            folders = source.list_folders()
            targets: list[FolderInfo] = []
            for name in cfg.folders:
                found = next((f for f in folders if settings.folder_selected(f.name, [name])), None)
                if found is None:
                    report.folders[name] = {"missing": True}
                    continue
                if settings.is_hard_excluded(found.name, found.flags, found.delimiter):
                    continue
                if found not in targets:
                    targets.append(found)
            i = 0
            while i < len(targets) and not self._stop.is_set():
                try:
                    self._scan_folder(source, targets[i], cfg, report)
                except RunAbort as e:
                    self._fail(report, str(e))
                    break
                except MailConnectError as e:
                    # Bridge restarts and dropped connections are routine: the
                    # folder saved its cursor, so reconnect once and retry it.
                    # A second failure, or a failing reconnect, ends the run.
                    if report.reconnects or e.kind not in ("network", "protocol"):
                        raise
                    self._log.info("mail: %s failed (%s); reconnecting once",
                                   targets[i].name, e)
                    report.reconnects += 1
                    try:
                        source.close()
                    except Exception:  # noqa: BLE001 — closing a dead connection
                        pass
                    source = self._source_factory(self._imap_config(cfg), password)
                    continue
                i += 1
            if self._stop.is_set() and report.ok:
                report.skipped_reason = "stopping"
        except MailConnectError as e:
            self._fail(report, str(e))
        finally:
            try:
                source.close()
            except Exception:  # noqa: BLE001 — closing a dead connection
                pass

    def _scan_folder(self, source, folder: FolderInfo, cfg: MailConfig, report: RunReport) -> None:
        """Read one folder from its cursor.

        A folder is read in one of two modes. Normal: every UID after the
        cursor. Window: by date — the first scan (since the backfill start),
        a rescan after UIDVALIDITY changed (since before the last scan), or a
        window an earlier run did not finish (since its stored date, above its
        stored UID). A window that runs to the end moves the cursor to
        UIDNEXT - 1, so the old mail it skipped by date is not picked up as
        "new" next time; one that stops early stores its date to carry on.
        """
        host = self._host
        state = source.select(folder)
        cur = host.mail(store.mail_get_cursor, folder.name)
        now = self._clock()
        backfill_since = (now - timedelta(days=cfg.backfill_days)).date()
        same_validity = cur is not None and cur["uidvalidity"] == state.uidvalidity
        rescan = False
        since: date | None = None
        if cur is None:
            since, floor = backfill_since, 0
        elif not same_validity:
            # The server renumbered the folder: every UID we remember is
            # meaningless. Search by date instead, from before the last scan,
            # and let the ledger (keyed by Message-ID) drop what was seen.
            last_scan = _parse_stamp(cur["last_scan_at"])
            since = backfill_since
            if last_scan is not None:
                since = min(backfill_since, (last_scan - timedelta(days=1)).date())
            self._log.info("mail: UIDVALIDITY of %s changed (%s → %s); rescanning since %s",
                           folder.name, cur["uidvalidity"], state.uidvalidity, since.isoformat())
            floor = 0
            rescan = True
        elif cur["window_since"]:
            try:
                since = date.fromisoformat(cur["window_since"])
            except ValueError:
                since = backfill_since
            floor = cur["last_uid"]
        else:
            floor = cur["last_uid"]
        window = since is not None
        if window:
            found = source.search_uids(since=since)
        else:
            found = source.search_uids(after_uid=floor)
        found = sorted(u for u in found if u > floor)
        truncated = len(found) > MAX_PER_FOLDER_PER_RUN
        uids = found[:MAX_PER_FOLDER_PER_RUN]

        info = {"uidvalidity": state.uidvalidity, "fetched": 0, "last_uid": floor,
                "rescanned": rescan}
        report.folders[folder.name] = info
        last_good = floor
        complete = False
        try:
            for m in source.fetch(uids, max_bytes=MAX_MESSAGE_BYTES):
                if self._stop.is_set():
                    break
                info["fetched"] += 1
                if m.raw is None:
                    self._skip_oversize(folder, state.uidvalidity, m.uid)
                    report.counts["skipped"] = report.counts.get("skipped", 0) + 1
                    last_good = m.uid
                    continue
                out = self.process_message(folder, m.raw, uid=m.uid,
                                           internaldate=m.internaldate, config=cfg)
                report.counts[out.outcome] = report.counts.get(out.outcome, 0) + 1
                if out.transient:
                    # Stop here: the cursor must not pass a message nobody read.
                    info["error"] = out.detail
                    report.ok = False
                    report.error = out.detail
                    self._log.info("mail: %s uid %s will be retried (%s)",
                                   folder.name, m.uid, out.detail)
                    break
                last_good = m.uid
            else:
                complete = True
        finally:
            # Save what was achieved — unless nothing was, and the loop stopped
            # early: the cursor (or its absence) then still says where to
            # start, which saving would only blur.
            window_since = None
            if complete:
                # Every UID asked for was read or is gone (expunged between the
                # search and the fetch), so the cursor may pass all of them.
                last_uid = max(last_good, floor, uids[-1] if uids else 0)
                if window and truncated:
                    window_since = since.isoformat()
                elif (window or not uids) and state.uidnext:
                    last_uid = max(last_uid, state.uidnext - 1)
            else:
                last_uid = max(last_good, floor)
                if window:
                    window_since = since.isoformat()
            if complete or last_good > floor:
                info["last_uid"] = last_uid
                host.mail(store.mail_set_cursor, folder.name, uidvalidity=state.uidvalidity,
                          last_uid=last_uid, last_scan_at=_iso(self._clock()),
                          window_since=window_since)

    def _skip_oversize(self, folder: FolderInfo, uidvalidity: int, uid: int) -> None:
        key = f"oversize:{folder.name}:{uidvalidity}:{uid}"

        def write(conn):
            with store.tx(conn):
                if store.mail_claim(conn, key, message_id=None, thread_id=key,
                                    folder=folder.name, uid=uid):
                    store.mail_settle(conn, key, stage="fetch", outcome="skipped",
                                      detail="larger than 8 MB")
        self._host.mail(write)
        self._log.info("mail: %s uid %s skipped: larger than 8 MB", folder.name, uid)

    def _write_status(self, report: RunReport) -> None:
        patch = {
            "last_run_started": report.started_at,
            "last_run_finished": report.finished_at,
            "last_error": None if report.ok else (report.error or "the run failed"),
            "last_counts": report.counts,
            "last_folders": report.folders,
        }
        if report.ok:
            patch["last_ok_at"] = report.finished_at
        try:
            self._host.mail(store.merge_meta_json, MAIL_STATUS_KEY, patch)
            # Simplest correct rule: every run that did anything tells the tabs.
            self._host.publish_mail_changed()
        except Exception as exc:  # noqa: BLE001
            self._log.warning("mail: could not record the run status: %s", redact_exc(exc))

    # ── one message ──

    def process_message(self, folder: FolderInfo, raw: bytes, *, uid: int | None = None,
                        internaldate: datetime | None = None,
                        config: MailConfig | None = None) -> Outcome:
        """Decide what one message becomes, and record it in the ledger.

        Raises only `RunAbort`; every other failure is an `Outcome`.
        """
        cfg = config or self.config()
        try:
            msg = message.parse_message(raw)
            key = message.ledger_key(msg)
            tid = message.thread_id(msg)
        except Exception as exc:  # noqa: BLE001 — one bad message must not stall the folder
            return self._unreadable(folder, raw, uid, exc)
        claimed = self._host.mail(store.mail_claim, key, message_id=msg.message_id,
                                  thread_id=tid, folder=folder.name, uid=uid)
        if not claimed:
            return self._claim_lost(key)
        c = _Msg(folder=folder, msg=msg, key=key, tid=tid, internaldate=internaldate, cfg=cfg)
        try:
            out = self._stages(c)
        except RunAbort:
            raise
        except Exception as exc:  # noqa: BLE001 — one bad message must not stall the folder
            detail = redact_exc(exc)
            self._log.warning("mail: %s in %s failed: %s", key, folder.name, detail)
            out = self._settle(c, "error", "error", detail, extra=False)
        self._log.info("mail: %s in %s: %s/%s", key, folder.name, out.stage, out.outcome)
        return out

    def _claim_lost(self, key: str) -> Outcome:
        """The outcome for a message whose key is already in the ledger.

        Settled: a decision, so a duplicate. Unsettled: another caller is
        still working on it, or died doing so — retried later, never counted
        as done, or the cursor would pass a message nobody read.
        """
        row = self._host.mail(store.mail_ledger_get, key)
        if row is None or row["settled_at"] is None:
            return Outcome("ledger", "retry", "an unfinished run holds this message",
                           transient=True)
        return Outcome("ledger", "duplicate", "already processed")

    def _unreadable(self, folder: FolderInfo, raw: bytes, uid: int | None,
                    exc: Exception) -> Outcome:
        """Settle a message that could not even be parsed, under a hash of its bytes.

        There is no Message-ID to key it by, and leaving it unsettled would
        stop the folder at it on every run.
        """
        key = "hash:" + hashlib.sha256(raw).hexdigest()
        detail = redact_exc(exc)[:300]
        self._log.warning("mail: %s in %s could not be read: %s", key, folder.name, detail)

        def write(conn):
            with store.tx(conn):
                if not store.mail_claim(conn, key, message_id=None, thread_id=key,
                                        folder=folder.name, uid=uid):
                    return False
                store.mail_settle(conn, key, stage="error", outcome="error", detail=detail)
                return True
        if not self._host.mail(write):
            return self._claim_lost(key)
        return Outcome("error", "error", detail)

    def _settle(self, c: _Msg, stage: str, outcome: str, detail: str = "", *,
                suggestion_id: str | None = None, extra: bool = True) -> Outcome:
        d = _detail(detail, c.extra if extra else ())
        self._host.mail(store.mail_settle, c.key, stage=stage, outcome=outcome,
                        detail=d or None, suggestion_id=suggestion_id)
        return Outcome(stage, outcome, d, suggestion_id=suggestion_id)

    def _release(self, c: _Msg) -> None:
        self._host.mail(store.mail_release, c.key)

    def _llm_failed(self, c: _Msg, stage: str, e: LlmError) -> Outcome:
        if e.kind == "transient":
            self._release(c)
            return Outcome(stage, "retry", str(e), transient=True)
        if e.kind == "config":
            self._release(c)
            raise RunAbort(str(e))
        return self._settle(c, stage, "error", str(e))

    def _stages(self, c: _Msg) -> Outcome:
        host, cfg, msg = self._host, c.cfg, c.msg

        # 1. ledger: a message the owner rejected stays rejected, in any folder.
        if host.mail(store.mail_is_rejected_message, c.key):
            return self._settle(c, "ledger", "suppressed", "rejected before")

        # 2. folder scope
        f = c.folder
        if (settings.is_hard_excluded(f.name, f.flags, f.delimiter)
                or not settings.folder_selected(f.name, cfg.folders)):
            return self._settle(c, "folder", "skipped", f"folder {f.name} is not scanned")

        # 3. self-mail
        sender = msg.from_addr
        if not sender:
            return self._settle(c, "self", "skipped", "no usable From address")
        note_to_self = False
        if addresses.is_self(sender, cfg.self_addresses):
            recipients = msg.to + msg.cc
            if (cfg.capture_notes_to_self and recipients
                    and all(addresses.is_self(r, cfg.self_addresses) for r in recipients)):
                note_to_self = True
            else:
                return self._settle(c, "self", "skipped", "sent by you")

        # 4. never_parse
        p = addresses.matches_any(sender, cfg.never_parse)
        if p:
            return self._settle(c, "never", "skipped", f"never_parse {p}")

        # 5. always_parse — only for mail a trusted server authenticated
        bypass_bulk = False
        always_detail = ""
        p = addresses.matches_any(sender, cfg.always_parse)
        if p:
            v = authres.verify_sender(msg.headers, sender, msg.from_count, cfg.trusted_authserv_ids)
            bypass_bulk = v.passed
            always_detail = f"always_parse {p}: {v.reason}"
            if not v.passed:
                self._log.info("mail: %s matches always_parse but sender authentication did not "
                               "pass (%s); treating as ordinary mail", c.key, v.reason)

        # 6. bulk
        if not (bypass_bulk or note_to_self):
            bulk = self._bulk_reason(msg, sender)
            if bulk:
                return self._settle(c, "bulk", "skipped", _detail(bulk, [always_detail]))
        if always_detail:
            c.extra.append(always_detail)

        # 7. fast paths
        hit = fastpaths.run(msg)
        if hit:
            return self._stage_fastpath(c, *hit)

        # 8. extraction
        body = message.strip_quotes(msg.text[:MAX_STRIP_CHARS], subject=msg.subject)
        if not body.strip():
            return self._settle(c, "extract", "not_actionable",
                                "nothing left after removing quoted text")
        if len(body) > cfg.body_max_chars:
            body = body[:cfg.body_max_chars] + "\n[…truncated]"
        try:
            ex = self.llm.extract(EmailForExtraction(
                sender_name=msg.from_name, sender_addr=sender, subject=msg.subject,
                sent=c.sent, body=body))
        except LlmError as e:
            return self._llm_failed(c, "extract", e)
        if not ex.is_actionable:
            return self._settle(c, "extract", "not_actionable", f"confidence {ex.confidence:.2f}")

        kind, why = self._decide_kind(c, ex, body)
        c.extra.append(why)

        # 9 + 10. dedup, then stage
        return self._dedup(c, ex, kind)

    @staticmethod
    def _bulk_reason(msg: ParsedMessage, sender: str) -> str | None:
        if message.header_value(msg, "List-Unsubscribe") is not None:
            return "List-Unsubscribe"
        precedence = (message.header_value(msg, "Precedence") or "").strip().lower()
        if precedence in _BULK_PRECEDENCE:
            return f"Precedence: {precedence}"
        auto = message.header_value(msg, "Auto-Submitted")
        if auto is not None:
            value = auto.split(";", 1)[0].strip().lower()
            if value != "no":
                return f"Auto-Submitted: {value[:60]}"
        if addresses.noreply_local_part(sender):
            return "no-reply sender"
        return None

    def _jev_ready(self, decider: str) -> bool:
        """Is `decider` "jev" and a TypeSafe key set? Otherwise the model decides."""
        return decider == "jev" and self._secrets.status("typesafe_api_key").set

    def _decide_kind(self, c: _Msg, ex: Extraction, body: str) -> tuple[str, str]:
        cfg, msg = c.cfg, c.msg
        if self._jev_ready(cfg.kind_decider):
            sender = (f"{msg.from_name} <{msg.from_addr}>" if msg.from_name
                      else (msg.from_addr or ""))
            sent = c.sent.date().isoformat() if c.sent else ""
            try:
                v = self.jev.decide_kind(sender=sender, subject=msg.subject, sent=sent, body=body)
                if v.agreed and v.confidence >= JEV_MIN_CONFIDENCE:
                    kind, why = v.kind, f"Jev chose {v.kind} ({v.confidence:.2f}, {v.model})"
                else:
                    kind, why = ex.kind, f"Jev unsure ({v.confidence:.2f}); kept the model's {ex.kind}"
            except Exception as e:  # noqa: BLE001 — Jev failing never stops the pipeline
                reason = str(e) if isinstance(e, (JevError, SecretStoreError)) else redact_exc(e)
                if not isinstance(e, JevError):
                    self._log.warning("mail: asking Jev about %s failed: %s", c.key, reason)
                kind, why = ex.kind, f"Jev unavailable ({reason}); kept the model's {ex.kind}"
        else:
            # "jev" without a key lands here too; kindrules treats it as "model".
            facts = kindrules.KindFacts(
                sender=msg.from_addr, subject=msg.subject, body=body, model_kind=ex.kind,
                has_time=isinstance(ex.event_start, datetime),
                has_date=ex.event_start is not None or ex.due is not None,
                has_location=bool(ex.location))
            kind, why = kindrules.decide(cfg.kind_decider, kindrules.load_rules(cfg.kind_rules),
                                         facts)
        if kind == "event" and ex.event_start is None:
            kind, why = "task", why + "; no start time, kept as a task"
        return kind, why

    # ── dedup ──

    def _dedup(self, c: _Msg, ex: Extraction, kind: str) -> Outcome:
        host = self._host

        # a. the thread already feeds a pending suggestion: add to it
        th = host.mail(store.mail_get_thread, c.tid)
        if th is not None and th["suggestion_id"]:
            s = host.mail(store.mail_get_suggestion, th["suggestion_id"])
            if s is not None and s["status"] == "pending":
                return self._merge(c, s, ex, kind, keep_due=False, detail="same thread")

        # b. the owner dismissed this already — checked before the thread's
        #    task, or a dismissed update to that task comes back on every reply
        rejected = list(host.mail(store.mail_rejections_for_thread, c.tid))
        if rejected and any(_same_item(ex, r) for r in rejected):
            return self._settle(c, "dedup", "suppressed", "same as a dismissed suggestion")

        # b2. the thread's event is already on the calendar: a reply restating
        #     it is not a second event. Compared by day, since an event read
        #     from prose has a naive start; another day is a new suggestion the
        #     owner decides on — changes to an added event are not applied.
        if kind == "event":
            start = ex.event_start
            day = (start.date() if isinstance(start, datetime) else start).isoformat()
            if any(s["kind"] == "event" and s["status"] in ("approved", "approving")
                   and (s["event_start"] or "")[:10] == day
                   for s in host.mail(store.mail_suggestions_for_thread, c.tid)):
                return self._settle(c, "dedup", "duplicate", "already added as an event")

        # c. the thread became a task: propose an update to it (tasks only —
        #    an event in a task's thread is its own suggestion)
        if kind == "task" and th is not None and th["task_uid"]:
            task = host.get_task(th["task_list"], th["task_uid"])
            if task and not task["completed"] and not task["cancelled"]:
                fields = self._fields("update", c, ex=ex,
                                      target=(th["task_list"], th["task_uid"]))
                return self._stage(c, fields, "dedup", "update to the thread's task")

        # d. ask Jev or the model about whatever looks similar
        candidates: list[Candidate] = []
        targets: dict[str, Any] = {}
        if kind == "task":
            tasks = host.search_open_tasks_any(_terms(ex), limit=MAX_CANDIDATE_TASKS)
            for i, t in enumerate(tasks[:MAX_CANDIDATE_TASKS], 1):
                label = f"T{i}"
                candidates.append(Candidate(label, t["summary"] or "", t.get("notes") or "",
                                            t.get("due")))
                targets[label] = t
        pending = host.mail(store.mail_list_suggestions, status="pending", limit=200)
        scored = [(_overlap(ex.title, s["title"]), i, s) for i, s in enumerate(pending)]
        scored = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1]))
        for i, (_, _, s) in enumerate(scored[:MAX_CANDIDATE_SUGGESTIONS], 1):
            label = f"S{i}"
            candidates.append(Candidate(label, s["title"], s["notes"] or "", s["due"]))
            targets[label] = s
        for i, r in enumerate(list(reversed(rejected))[:MAX_CANDIDATE_REJECTIONS], 1):
            label = f"R{i}"
            candidates.append(Candidate(label, r["title"], "", r["due"]))
            targets[label] = r
        if not candidates:
            return self._stage_new(c, ex, kind)

        m = self._jev_match(c, ex, candidates) if self._jev_ready(c.cfg.dedup_decider) else None
        if m is None:
            try:
                m = self.llm.match(ex, candidates)
            except LlmError as e:
                if e.kind in ("transient", "config"):
                    return self._llm_failed(c, "dedup", e)
                self._log.warning("mail: dedup check for %s failed (%s); treating it as new",
                                  c.key, e)
                m = Match("new", None)

        target = m.target
        if m.decision == "new" or target not in targets:
            return self._stage_new(c, ex, kind)
        if target.startswith("R"):
            return self._settle(c, "dedup", "suppressed", "same as a dismissed suggestion")
        if target.startswith("T"):
            task = targets[target]
            href = host.resolve_list(task["list"], component="VTODO")
            if m.decision == "duplicate":
                d = _detail("same as an open task", c.extra)

                def write(conn):
                    with store.tx(conn):
                        if href:
                            store.mail_upsert_thread(conn, c.tid, task_list=href,
                                                     task_uid=task["uid"])
                        store.mail_settle(conn, c.key, stage="dedup", outcome="duplicate",
                                          detail=d)
                host.mail(write)
                return Outcome("dedup", "duplicate", d)
            if href is None:
                return self._stage_new(c, ex, kind)
            fields = self._fields("update", c, ex=ex, target=(href, task["uid"]))
            return self._stage(c, fields, "dedup", "update to an open task")
        s = targets[target]
        if m.decision == "duplicate":
            return self._merge(c, s, ex, kind, keep_due=True,
                               detail="same as a pending suggestion")
        return self._merge(c, s, ex, kind, keep_due=False, detail="update to a pending suggestion")

    def _jev_match(self, c: _Msg, ex: Extraction, candidates: list[Candidate]) -> Match | None:
        """Jev's answer to the dedup question as a `Match`, or None when Claude should decide.

        The same decision as `dev/mail_eval.py::decide_dedup`: in the unsure band
        Claude decides; below `SAME_T` it is new work; otherwise the deadline is
        compared here (Jev is weak at dates) and Jev's "changed" settles the rest.
        Either way the reason goes on the ledger detail.
        """
        item = {"label": "new", "title": ex.title, "notes": ex.notes,
                "due": ex.due.isoformat() if ex.due else None}
        cands = [{"label": x.label, "title": x.title, "notes": x.notes, "due": x.due}
                 for x in candidates]
        try:
            jm = self.jev.match(item, cands)
        except Exception as e:  # noqa: BLE001 — Jev failing never stops the pipeline
            reason = str(e) if isinstance(e, JevError) else redact_exc(e)
            level = logging.INFO if isinstance(e, JevError) else logging.WARNING
            self._log.log(level, "mail: Jev dedup check for %s failed (%s); asking Claude",
                          c.key, reason)
            c.extra.append(f"Jev unavailable ({reason}); asked Claude")
            return None
        if jm.unsure:
            c.extra.append(f"Jev unsure (p={jm.p:.2f}); asked Claude")
            return None
        c.extra.append(f"Jev p={jm.p:.2f} ({jm.model})")
        if jm.target is None:
            return Match("new", None)
        cand = next(x for x in cands if x["label"] == jm.target)
        # Compared by DAY: an email names a date, while an open task's due may be
        # timed ("2026-10-09T17:00:00+02:00"), and that is not a moved deadline.
        moved = item["due"] is not None and item["due"][:10] != (cand["due"] or "")[:10]
        changed = (jm.changed or 0.0) >= JEV_CHANGED_T
        return Match("update" if moved or changed else "duplicate", jm.target)

    def _update_entry(self, c: _Msg, *, notes: str, due: str | None) -> dict:
        """One `updates` entry: a later message merged into a suggestion."""
        return {
            "message_key": c.key, "message_id": c.msg.message_id, "sender": c.msg.from_addr,
            "sender_name": c.msg.from_name or "",
            "subject": c.msg.subject, "sent_at": c.sent.isoformat() if c.sent else None,
            "notes": notes, "due": due, "thread_id": c.tid,
        }

    def _merge(self, c: _Msg, s, ex: Extraction, kind: str, *, keep_due: bool,
               detail: str) -> Outcome:
        """Record this message on pending suggestion `s` instead of staging a new one.

        `s` was read before the slow dedup question; the owner may have
        approved or rejected it since. Re-read in the write's transaction, and
        if it is no longer pending the message becomes a suggestion of its
        own: writing into a decided suggestion would change a rejected row or
        add notes no approval will ever carry.
        """
        sid = s["id"]
        entry = self._update_entry(c, notes="" if keep_due else ex.notes,
                                   due=ex.due.isoformat() if ex.due else None)
        d = _detail(detail, c.extra)

        def write(conn):
            with store.tx(conn):
                row = store.mail_get_suggestion(conn, sid)
                if row is None or row["status"] != "pending":
                    return False
                patch: dict[str, Any] = {"updates": [*_load_updates(row["updates"]), entry]}
                if (not keep_due and ex.due and row["kind"] in ("task", "update")
                        and ex.due.isoformat() != row["due"]):
                    patch["due"] = ex.due.isoformat()
                store.mail_update_suggestion(conn, sid, **patch)
                store.mail_upsert_thread(conn, c.tid, suggestion_id=sid)
                store.mail_settle(conn, c.key, stage="dedup", outcome="attached", detail=d,
                                  suggestion_id=sid)
                return True
        if not self._host.mail(write):
            return self._stage_new(c, ex, kind)
        return Outcome("dedup", "attached", d, suggestion_id=sid)

    # ── staging ──

    def _fields(self, kind: str, c: _Msg, *, ex: Extraction | None = None, proposal=None,
                target: tuple[str, str] | None = None) -> dict:
        """The columns of a new suggestion of `kind` (task, update or event)."""
        msg, sent = c.msg, c.sent
        out: dict[str, Any] = {
            "kind": kind,
            "sender": msg.from_addr, "sender_name": msg.from_name, "subject": msg.subject,
            "sent_at": sent.isoformat() if sent else None,
            "message_key": c.key, "message_id": msg.message_id, "thread_id": c.tid,
            "folder": c.folder.name,
        }
        if proposal is not None:
            out.update(
                title=proposal.summary, notes=proposal.description, due=None, confidence=None,
                event_start=proposal.start.isoformat(),
                event_end=proposal.end.isoformat() if proposal.end else None,
                event_all_day=int(proposal.all_day), location=proposal.location or None,
                ics_uid=proposal.uid, event_rrule=proposal.rrule)
        elif kind == "event":
            out.update(
                title=ex.title, notes=ex.notes, due=None, confidence=ex.confidence,
                event_start=ex.event_start.isoformat(),
                event_end=ex.event_end.isoformat() if ex.event_end else None,
                event_all_day=int(_all_day(ex.event_start)), location=ex.location or None)
        else:
            out.update(title=ex.title, notes=ex.notes,
                       due=ex.due.isoformat() if ex.due else None, confidence=ex.confidence)
        if target is not None:
            out.update(target_list=target[0], target_uid=target[1])
        return out

    def _stage(self, c: _Msg, fields: dict, stage: str, detail: str) -> Outcome:
        """Insert one suggestion, point the thread at it and settle — one transaction."""
        sid = uuid.uuid4().hex
        d = _detail(detail, c.extra)

        def write(conn):
            with store.tx(conn):
                store.mail_insert_suggestion(conn, sid, fields)
                store.mail_upsert_thread(conn, c.tid, suggestion_id=sid)
                store.mail_settle(conn, c.key, stage=stage, outcome="staged", detail=d or None,
                                  suggestion_id=sid)
        self._host.mail(write)
        return Outcome(stage, "staged", d, suggestion_id=sid)

    def _stage_new(self, c: _Msg, ex: Extraction, kind: str) -> Outcome:
        out = self._stage(c, self._fields(kind, c, ex=ex), "stage", "")
        cfg = c.cfg
        # The auto-accept hook. Off unless the owner sets a threshold, and
        # never for events: a calendar entry blocks time on its own.
        if (cfg.auto_accept_min_confidence is not None and kind == "task"
                and ex.confidence >= cfg.auto_accept_min_confidence):
            try:
                review.approve(self._host, out.suggestion_id, config=cfg)
            except Exception as e:  # noqa: BLE001 — the suggestion stays pending
                reason = str(e) if isinstance(e, review.ReviewError) else redact_exc(e)
                self._log.warning("mail: auto-accept of %s failed: %s", out.suggestion_id, reason)
        return out

    def _stage_fastpath(self, c: _Msg, name: str, proposals: list) -> Outcome:
        """Stage an invite's events, or apply them to the suggestion its UID already has.

        Per event with a UID the earlier suggestion decides: dismissed — it
        stays dismissed; still pending — a reschedule or a new place is
        written onto it (the owner approves the current version); already
        added — nothing, because changing an event in the owner's calendar
        from an email is not this pipeline's job.
        """
        fields = [(p, self._fields("event", c, proposal=p))
                  for p in proposals[:MAX_FASTPATH_EVENTS]]
        compared = ("title", "event_start", "event_end", "event_all_day", "location")

        def write(conn):
            with store.tx(conn):
                ids: list[str] = []
                updated: list[str] = []
                dup = added = False
                for p, f in fields:
                    old = store.mail_find_suggestion_by_ics_uid(conn, p.uid) if p.uid else None
                    if old is None:
                        sid = uuid.uuid4().hex
                        store.mail_insert_suggestion(conn, sid, f)
                        ids.append(sid)
                    elif old["status"] == "rejected":
                        continue                    # the owner's "no" stands
                    elif old["status"] != "pending":
                        added = True
                    elif all(old[k] == f[k] for k in compared):
                        dup = True
                    else:
                        change = f"Changed: {f['event_start']}"
                        if f["location"]:
                            change += f" at {f['location']}"
                        entry = self._update_entry(c, notes=change, due=None)
                        store.mail_update_suggestion(
                            conn, old["id"], **{k: f[k] for k in compared},
                            updates=[*_load_updates(old["updates"]), entry])
                        updated.append(old["id"])
                if ids:
                    d = _detail(f"{len(ids)} event(s) from {name}", c.extra)
                    stage, outcome, sid = "fastpath", "staged", ids[0]
                elif updated:
                    d = _detail("updated the pending invitation", c.extra)
                    stage, outcome, sid = "fastpath", "attached", updated[0]
                elif dup or added:
                    d = _detail("event already suggested" if dup else
                                "already added; changes to an added event are not applied",
                                c.extra)
                    stage, outcome, sid = "fastpath", "duplicate", None
                else:
                    d = _detail("the invitation was dismissed before", c.extra)
                    stage, outcome, sid = "fastpath", "suppressed", None
                if sid is not None:
                    store.mail_upsert_thread(conn, c.tid, suggestion_id=sid)
                store.mail_settle(conn, c.key, stage=stage, outcome=outcome, detail=d,
                                  suggestion_id=sid)
                return Outcome(stage, outcome, d, suggestion_id=sid)
        return self._host.mail(write)

    # ── settings page ──

    def test_imap(self) -> dict:
        """Log in, list folders and look at the Authentication-Results of the
        newest INBOX messages (up to `AUTHRES_SAMPLE`: one message may predate a
        change of server, or be a note to self that never passed an MTA).

        Raises `MailConnectError` / `SecretStoreError` for the route to report.
        """
        cfg = self.config()
        password = self._secrets.get("imap_password")
        if not password:
            raise MailConnectError("no IMAP password is set", kind="config")
        self._check_binding(cfg)
        source = self._source_factory(self._imap_config(cfg), password)
        try:
            folders = source.list_folders()
            sample: list[int] = []
            ids: list[str] = []
            trusted = False
            inbox = next((f for f in folders if settings.folder_selected(f.name, ["INBOX"])), None)
            if inbox is not None:
                source.select(inbox)
                sample = sorted(source.search_uids())[-AUTHRES_SAMPLE:]
                for uid in reversed(sample):                # newest first
                    hdr = source.fetch_header_fields(uid, ["AUTHENTICATION-RESULTS"])
                    parsed = email.message_from_bytes(hdr)
                    for i in authres.authserv_ids(parsed):
                        if i not in ids:
                            ids.append(i)
                    if authres.trusted_only(authres.collect(parsed), cfg.trusted_authserv_ids):
                        trusted = True
        finally:
            try:
                source.close()
            except Exception:  # noqa: BLE001
                pass
        return {
            "ok": True,
            "detail": f"Logged in as {cfg.imap_username}; {len(folders)} folders.",
            "folders": [{
                "name": f.name,
                "special": sorted(_SPECIAL_USE[x] for x in f.flags if x in _SPECIAL_USE),
                "excluded": settings.is_hard_excluded(f.name, f.flags, f.delimiter),
                "selected": settings.folder_selected(f.name, cfg.folders),
            } for f in folders],
            "auth_results": {"checked": bool(sample), "present": bool(ids),
                             "authserv_ids": ids, "trusted": trusted, "sampled": len(sample)},
        }

    def status(self) -> dict:
        cfg = self.config()
        host = self._host
        return {
            **host.mail(store.get_meta_json, MAIL_STATUS_KEY),
            "enabled": cfg.enabled,
            "deployment_enabled": self._deployment_enabled,
            "running": self._run_lock.locked(),
            "pending_count": host.mail(store.mail_count_suggestions, "pending"),
            "cursors": host.mail(store.mail_list_cursors),
            "counts": host.mail(store.mail_ledger_counts),
        }
