"""Evaluate TypeSafe Jev for two jobs in the email pipeline, against labelled data.

    python dev/mail_eval.py [--emails dev/mail_eval/emails.jsonl] [--dedup dev/mail_eval/dedup.jsonl]
                            [--out dev/mail_eval/results.json] [--claude]

Two questions, each a candidate for handing a Claude call to Jev:

1. PRE-FILTER. Before the extraction call, ask Jev whether the email asks the
   owner to do something or invites them to something, and skip the Claude call
   when it is confidently "no". The metric that decides it is the one a filter
   cannot get wrong: how many ACTIONABLE emails it would drop (each one is a
   task the owner never sees). Savings — the share of non-actionable mail it
   lets through to nobody — only count once that is ~zero.

2. DEDUP. Replace the second Claude call ("is this new, a duplicate of C2, or an
   update to C2?") with Jev. The deadline comparison stays in code (Jev is weak
   at dates by its own documentation); Jev answers only "which candidate, if
   any, is the same piece of work" and "does it add details".

Labels come from the synthetic, blind-adjudicated sets in dev/mail_eval/ (all
fictional domains). Cases whose generator and adjudicator disagreed, or that
either marked borderline, are reported separately from the clean set.

With --claude and SMYLTE_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) set, the same
cases also run through smylted.mail.llm.LlmClient — the production extraction
and match calls — so the two can be compared on one machine. It also measures
the extraction's categories: requests the category gate dropped, titles that
still carry a date, due dates that differ from the label, and labelled
actionable mail the bulk filter would drop before the model. TYPESAFE_API_KEY
(or SMYLTE_TYPESAFE_API_KEY) is required for the Jev half.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API = "https://api.typesafe.ai/v1/systemone"
# A month name with a day, a day with a month name, a numeric or ISO date,
# "today" and friends, a weekday: what a title should not carry. Whole words
# only, so "Mark 3 essays" is not a date; a weekday in a name ("Black Friday")
# is a false hit, which is why the report lists ids for a person to look at.
_MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
           r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
           r"|januar|februar|märz|mai|juni|juli|okt(?:ober)?|dez(?:ember)?)")
_WEEKDAYS = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday"
             r"|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag)")
DATE_IN_TITLE = re.compile(
    rf"\b{_MONTHS}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th|\.)?\s*(?:of\s+)?{_MONTHS}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}\.\d{1,2}\.(?:\d{2,4})?"
    r"|\b(?:today|tomorrow|tonight|heute|morgen)\b"
    rf"|\b{_WEEKDAYS}\b|\b(?:by|due|on|bis|am)\s+(?:mon|tue|wed|thu|fri|sat|sun)\b", re.I)
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
# A fictional owner's task lists, fixed so runs compare; every email is read as
# if they were this owner's (the lists the model may file a task under).
OWNER_LISTS = ("Home", "Work", "Mitchell Web Studio", "HIST 210", "MATH 240", "AP Psychology",
               "Personal Finance", "Spanish III", "Statistics", "Yearbook", "Student Press",
               "Family")
# Opening verbs the owner leaves off an assignment's name.
BOILERPLATE_VERB = re.compile(
    r"^(complete|submit|finish|do|turn in|prepare for|study for|fill out)\b", re.I)
_QUOTES = str.maketrans("", "", "\"\u201c\u201d'\u2018\u2019")

# ── pre-filter questions ─────────────────────────────────────────────────────
PRE_NOUL = {
    "type": "noul",
    "instructions": "Does `email` ask the owner to do something concrete, or tell the owner about an appointment or event they are expected to attend?",
    "criteria": {
        "true": "It asks the owner to act (reply, pay, sign, submit, bring, book, review, decide, call, pick up), or tells them about an appointment or event they should attend or keep free.",
        "false": "Nothing is asked of the owner: a newsletter, receipt, shipping update, automated notice that needs nothing, marketing, an FYI, a thank-you, an out-of-office reply or a calendar acceptance.",
    },
}
PRE_CHOICE = {
    "type": "choice",
    "instructions": "What does `email` ask of the owner?",
    "criteria": {
        "request": "It asks the owner to do something concrete: reply, pay, sign, submit, bring, book, review, decide, call, pick up.",
        "invitation": "It tells the owner about an appointment or event they are expected to attend or keep free.",
        "nothing": "Nothing is asked of the owner: a newsletter, receipt, shipping update, automated notice that needs nothing, marketing, an FYI, a thank-you, an out-of-office reply or a calendar acceptance.",
    },
}
KIND_CRITERIA = {
    "event": "Something that happens at a particular time the owner should attend or keep free: a meeting, appointment, parent evening, match, call.",
    "task": "Work the owner has to do, with or without a deadline: reply, pay, sign, submit, bring, book, review, decide.",
}
KIND_INSTRUCTIONS = "Should the request in `email` go on the owner's calendar as an event, or on their to-do list as a task?"


def _key(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return None


class Jev:
    def __init__(self, key: str):
        self._http = httpx.Client(timeout=60, headers={"Authorization": f"Bearer {key}"})
        self.calls = 0
        self.input_tokens = 0

    def ask(self, state, questions) -> dict:
        for attempt in range(5):
            r = self._http.post(API, json={"model": MODEL, "state": state, "questions": questions})
            if r.status_code in (429, 529) or r.status_code >= 500:
                time.sleep(min(2 ** attempt, 10))
                continue
            r.raise_for_status()
            data = r.json()
            self.calls += 1
            self.input_tokens += int((data.get("usage") or {}).get("input_tokens") or 0)
            return data["answers"]
        raise RuntimeError(f"TypeSafe kept failing: {r.status_code}")


def body_of(c: dict) -> str:
    """The body both models are given: quoted replies removed, as the pipeline
    removes them before either sees a message, then cut. A reply whose only
    date is in the quote it answers is read without it, as it is at home."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    from smylted.mail.message import strip_quotes  # noqa: E402
    return strip_quotes(c["body"], subject=c["subject"])[:8000]


def email_state(c: dict) -> dict:
    return {"email": {"from": f"{c['from_name']} <{c['from_addr']}>", "subject": c["subject"],
                      "sent": c["sent"], "body": body_of(c)}}


# ── pre-filter ───────────────────────────────────────────────────────────────
def run_prefilter(jev: Jev, cases: list[dict]) -> list[dict]:
    def one(c):
        crit_rev = dict(reversed(list(KIND_CRITERIA.items())))
        a = jev.ask(email_state(c), {
            "pre_noul": PRE_NOUL,
            "pre_choice": PRE_CHOICE,
            "kind_a": {"type": "choice", "instructions": KIND_INSTRUCTIONS, "criteria": KIND_CRITERIA},
            "kind_b": {"type": "choice", "instructions": KIND_INSTRUCTIONS, "criteria": crit_rev},
        })
        pc = a["pre_choice"]["probabilities"]
        ka, kb = a["kind_a"], a["kind_b"]
        kp = {k: (ka["probabilities"].get(k, 0) + kb["probabilities"].get(k, 0)) / 2 for k in KIND_CRITERIA}
        return {"id": c["id"],
                "p_noul": a["pre_noul"]["noul"],
                "p_choice_act": 1.0 - pc.get("nothing", 0.0),
                "choice": a["pre_choice"]["choice"], "choice_conf": a["pre_choice"]["confidence"],
                "kind": max(kp, key=kp.get), "kind_agreed": ka["choice"] == kb["choice"],
                "kind_conf": min(ka["confidence"], kb["confidence"]) if ka["choice"] == kb["choice"] else 0.0}
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, cases))


# ── dedup ────────────────────────────────────────────────────────────────────
def _item_text(x: dict) -> str:
    due = x.get("due") or "none"
    notes = (x.get("notes") or "").strip()
    return f"{x['title']} (due {due})" + (f" — {notes[:300]}" if notes else "")


SAME_T = 0.5            # a candidate is "the same work" at p >= this
UNSURE = (0.35, 0.65)   # best match in this band → ask Claude instead (hybrid mode)
CHANGED_T = 0.5         # the direct comparison says "changed" at p >= this

CHANGED_INSTRUCTIONS = "`new` and `existing` describe the same piece of work. Does `new` change anything about it?"
CHANGED_CRITERIA = {
    "same": "Nothing changes: `new` only rewords `existing`, or repeats details `existing` already has.",
    "changed": "Something changes or is added: a different or newly stated deadline, amount, place, time, quantity, recipient, or an extra requirement.",
}


def _item(x: dict) -> dict:
    return {"title": x["title"], "notes": x["notes"], "due": x["due"]}


def run_dedup(jev: Jev, cases: list[dict]) -> list[dict]:
    """Two Jev requests per case, mirroring smylted/mail/jev.py.

    1. One "same piece of work?" Noul per candidate, all in one request.
    2. Only when a candidate clears SAME_T: a direct Choice between `existing`
       and `new` — "same" or "changed" — asked in both option orders. An
       earlier variant asked "does `new_item` add details not in
       `candidates.Ck`?" inside the big state; Jev answered that poorly (it
       fired on rewordings), as its docs predict for indirection.
    The deadline comparison is code, never Jev.
    """
    def one(c):
        cands = c["candidates"]
        state = {"new_item": _item(c["new_item"]),
                 "candidates": {x["id"]: _item(x) for x in cands}}
        qs = {f"same_{x['id']}": {
            "type": "noul",
            "instructions": f"Is `new_item` the same piece of work as `candidates.{x['id']}` (the same action on the same thing for the same period)?"}
            for x in cands}
        a = jev.ask(state, qs)
        same = {x["id"]: a[f"same_{x['id']}"]["noul"] for x in cands}
        best, p = max(same.items(), key=lambda kv: kv[1])
        changed = None
        if p >= SAME_T:
            cand = next(x for x in cands if x["id"] == best)
            rev = dict(reversed(list(CHANGED_CRITERIA.items())))
            b = jev.ask({"existing": _item(cand), "new": _item(c["new_item"])}, {
                "changed_a": {"type": "choice", "instructions": CHANGED_INSTRUCTIONS, "criteria": CHANGED_CRITERIA},
                "changed_b": {"type": "choice", "instructions": CHANGED_INSTRUCTIONS, "criteria": rev}})
            changed = (b["changed_a"]["probabilities"]["changed"] + b["changed_b"]["probabilities"]["changed"]) / 2
        return {"id": c["id"], "same": same, "best": best, "p": p, "changed": changed}
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, cases))


def decide_dedup(c: dict, r: dict, claude: dict | None = None) -> tuple[str, str | None, str]:
    """(label, target, who decided). `claude` is that case's Claude match, for the hybrid."""
    if claude is not None and UNSURE[0] <= r["p"] < UNSURE[1]:
        return claude.get("label"), claude.get("target"), "claude"
    if r["p"] < SAME_T:
        return "new", None, "jev"
    cand = next(x for x in c["candidates"] if x["id"] == r["best"])
    if c["new_item"]["due"] and c["new_item"]["due"] != cand.get("due"):
        return "update", r["best"], "jev"
    return ("update" if (r["changed"] or 0.0) >= CHANGED_T else "duplicate"), r["best"], "jev"


# ── optional Claude baseline through the production client ───────────────────
def run_claude(emails: list[dict], dedup: list[dict]) -> dict | None:
    key = _key("SMYLTE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    if not key:
        return None
    sys.path.insert(0, str(HERE.parent))
    import anthropic  # noqa: E402
    from smylted.mail import filing  # noqa: E402
    from smylted.mail.llm import (IGNORED_CATEGORIES, Candidate, EmailForExtraction,  # noqa: E402
                                  Extraction, LlmClient)
    # Haiku only, deliberately not configurable here: this is a cost-bounded
    # comparison against the production default, not a model sweep.
    model = "claude-haiku-5-5"
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    spent = {"in": 0, "out": 0}

    def factory(*_a):
        client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com",
                                     default_headers=headers, max_retries=2, timeout=60.0)
        create = client.messages.create

        def counted(**kw):
            # Hard stop well under $2 at Haiku 5.5's $0.10 / $0.50 per Mtok (prompts
            # under 100k tokens, which every eval prompt is).
            if spent["in"] / 1e6 * 0.10 + spent["out"] / 1e6 * 0.50 > 2.0:
                raise RuntimeError("eval spending cap reached")
            r = create(**kw)
            spent["in"] += r.usage.input_tokens
            spent["out"] += r.usage.output_tokens
            return r
        client.messages.create = counted
        return client

    llm = LlmClient(api_key_provider=lambda: key, model_provider=lambda: model)
    llm.client_factory = factory
    out = {"model": model, "extract": {}, "match": {}, "usage": spent}
    owner_lists = [(n.lower(), n) for n in OWNER_LISTS]
    names = dict(owner_lists)
    for c in emails:
        sent = datetime.fromisoformat(c["sent"]) if c.get("sent") else None
        try:
            ex = llm.extract(EmailForExtraction(sender_name=c["from_name"], sender_addr=c["from_addr"],
                                                subject=c["subject"], sent=sent, body=body_of(c),
                                                lists=OWNER_LISTS))
            routed, title = "none", ex.title
            actionable = ex.is_actionable and ex.category not in IGNORED_CATEGORIES
            if actionable and ex.kind == "task":
                # As the pipeline does: only a task that passed the gate is filed and retitled.
                slug, _ = filing.route(ex.group, ex.list_name, owner_lists, {})
                routed = names[slug] if slug is not None else "none"
                if ex.category == "coursework":
                    title = filing.tidy_title(title, [n for n in (ex.group, routed if slug else "") if n])
            out["extract"][c["id"]] = {
                "actionable": actionable, "asked": ex.is_actionable, "kind": ex.kind, "category": ex.category,
                "title": title, "due": ex.due.isoformat() if ex.due else None,
                "group": ex.group, "list": routed, "picked": ex.list_name or "none"}
        except Exception as e:  # noqa: BLE001
            out["extract"][c["id"]] = {"error": str(e)}
    for c in dedup:
        ni = c["new_item"]
        item = Extraction(is_actionable=True, kind="task", title=ni["title"], notes=ni["notes"],
                          due=date.fromisoformat(ni["due"]) if ni["due"] else None,
                          event_start=None, event_end=None, location="", confidence=1.0)
        cands = [Candidate(label=x["id"].replace("C", "T"), title=x["title"], notes=x["notes"], due=x["due"])
                 for x in c["candidates"]]
        try:
            m = llm.match(item, cands)
            tgt = m.target.replace("T", "C") if m.target else None
            out["match"][c["id"]] = {"label": m.decision, "target": tgt}
        except Exception as e:  # noqa: BLE001
            out["match"][c["id"]] = {"error": str(e)}
    return out


# ── report ───────────────────────────────────────────────────────────────────
def report(out: dict, emails: list[dict], dedup: list[dict]) -> str:
    pre = {r["id"]: r for r in out["prefilter_raw"]}
    dd = {r["id"]: r for r in out["dedup_raw"]}
    cl = out.get("claude")
    # A results file saved before emails were added has no answers for them:
    # report on the ones it covers, and say how many it leaves out.
    covered = [e for e in emails if e["id"] in pre and (not cl or e["id"] in cl["extract"])]
    lines = []
    if len(covered) < len(emails):
        lines.append(f"(the results cover {len(covered)} of {len(emails)} emails; "
                     "the rest were added after they were saved)")
    emails = covered
    for name, cs in (("clean", [e for e in emails if e["clean"]]), ("all", emails)):
        act = [e for e in cs if e["gold"] == "actionable"]
        non = [e for e in cs if e["gold"] == "not_actionable"]
        lines.append(f"PRE-FILTER ({name}: {len(act)} actionable, {len(non)} not)")
        for t in (0.02, 0.05, 0.1, 0.2):
            drop = [e["id"] for e in act if pre[e["id"]]["p_noul"] < t]
            skip = sum(1 for e in non if pre[e["id"]]["p_noul"] < t)
            lines.append(f"  skip when p(yes) < {t}: drops {len(drop)} actionable {drop}, skips {skip}/{len(non)} non-actionable")
        if cl:
            miss = [e["id"] for e in act if not cl["extract"][e["id"]].get("actionable")]
            junk = [e["id"] for e in non if cl["extract"][e["id"]].get("actionable")]
            lines.append(f"  Claude extraction alone: misses {len(miss)} {miss}, junk suggestions {len(junk)}")
            gated = [e["id"] for e in act if cl["extract"][e["id"]].get("asked")
                     and not cl["extract"][e["id"]].get("actionable")]
            lines.append(f"  gated (the model saw a request, the category dropped it): "
                         f"{len(gated)} gold-actionable {gated}")
            dated = [e["id"] for e in cs if cl["extract"][e["id"]].get("actionable")
                     and DATE_IN_TITLE.search(cl["extract"][e["id"]].get("title") or "")]
            lines.append(f"  titles with a date: {len(dated)} {dated}")
            wrong = [f"{e['id']}: {cl['extract'][e['id']].get('due')} → {e['gold_due']}"
                     for e in cs if e.get("gold_kind") == "task" and e.get("gold_due")
                     and "due" in cl["extract"][e["id"]]
                     and cl["extract"][e["id"]].get("actionable")
                     and cl["extract"][e["id"]].get("due") != e["gold_due"]]
            lines.append(f"  due mismatches: {len(wrong)} {wrong}")
            # The bulk filter runs before the model, so the model cannot save these.
            sys.path.insert(0, str(HERE.parent))
            from smylted.mail.addresses import noreply_local_part  # noqa: E402
            dropped = [e["id"] for e in act if noreply_local_part(e["from_addr"])]
            lines.append(f"  gold actionable from no-reply senders "
                         f"(the bulk filter drops them before the model): {dropped}")
    if cl:
        def norm(t: str) -> str:
            return " ".join(t.translate(_QUOTES).casefold().split())
        got = lambda e, k: cl["extract"][e["id"]].get(k)  # noqa: E731
        want = [e for e in emails if e.get("gold_list")]
        wrong = [f"{e['id']}: {got(e, 'list')} → {e['gold_list']}" for e in want
                 if got(e, "list") != e["gold_list"]]
        lines.append(f"  lists right: {len(want) - len(wrong)}/{len(want)} (gold_list set) {wrong}")
        want = [e for e in emails if e.get("gold_title")]
        wrong = [f"{e['id']}: {got(e, 'title')} → {e['gold_title']}" for e in want
                 if norm(got(e, "title") or "") != norm(e["gold_title"])]
        lines.append(f"  titles exact: {len(want) - len(wrong)}/{len(want)} (gold_title set) {wrong}")
        verbs = [e["id"] for e in emails if got(e, "actionable") and got(e, "category") == "coursework"
                 and BOILERPLATE_VERB.match(got(e, "title") or "")]
        lines.append(f"  titles starting with a verb the owner drops: {verbs}")
    act = [e for e in emails if e["clean"] and e["gold"] == "actionable"]
    lines.append(f"KIND (clean actionable: {len(act)})")
    lines.append(f"  Jev alone: {sum(1 for e in act if pre[e['id']]['kind'] == e['gold_kind'])}")
    if cl:
        lines.append(f"  Claude alone: {sum(1 for e in act if cl['extract'][e['id']].get('kind') == e['gold_kind'])}")
        for conf in (0.5, 0.7, 0.9):
            hyb = sum(1 for e in act if (pre[e['id']]['kind'] if pre[e['id']]['kind_agreed'] and pre[e['id']]['kind_conf'] >= conf
                                         else cl['extract'][e['id']].get('kind')) == e['gold_kind'])
            lines.append(f"  Jev when confidence >= {conf}, else Claude: {hyb}")
    for name, cs in (("clean", [c for c in dedup if c["clean"]]), ("all", dedup)):
        lines.append(f"DEDUP ({name}: {len(cs)})")
        modes = [("Jev alone", None)]
        if cl:
            modes.append(("Jev, Claude when unsure", "hybrid"))
        for label, mode in modes:
            res = [(c, *decide_dedup(c, dd[c["id"]], cl["match"][c["id"]] if mode else None)) for c in cs]
            ok = sum(1 for c, lab, t, _ in res if lab == c["gold"] and (t or None) == (c["gold_target"] or None))
            sw = sum(1 for c, _, t, _ in res if c["gold"] == "new" and t)
            fb = sum(1 for *_, who in res if who == "claude")
            lines.append(f"  {label}: {ok}/{len(cs)} right, {sw} new items swallowed, {fb} handed to Claude")
        if cl:
            ok = sum(1 for c in cs if cl["match"][c["id"]].get("label") == c["gold"]
                     and (cl["match"][c["id"]].get("target") or None) == (c["gold_target"] or None))
            sw = sum(1 for c in cs if c["gold"] == "new" and cl["match"][c["id"]].get("target"))
            lines.append(f"  Claude alone: {ok}/{len(cs)} right, {sw} new items swallowed")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emails", default=str(HERE / "mail_eval" / "emails.jsonl"))
    ap.add_argument("--dedup", default=str(HERE / "mail_eval" / "dedup.jsonl"))
    ap.add_argument("--out", default=str(HERE / "mail_eval" / "results.json"))
    ap.add_argument("--claude", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="re-print the report from --out")
    args = ap.parse_args()
    if args.report_only:
        emails = [json.loads(l) for l in open(args.emails, encoding="utf-8") if l.strip()]
        dedup = [json.loads(l) for l in open(args.dedup, encoding="utf-8") if l.strip()]
        print(report(json.loads(Path(args.out).read_text(encoding="utf-8")), emails, dedup))
        return 0
    key = _key("SMYLTE_TYPESAFE_API_KEY", "TYPESAFE_API_KEY")
    if not key:
        print("set TYPESAFE_API_KEY", file=sys.stderr)
        return 1
    emails = [json.loads(l) for l in open(args.emails, encoding="utf-8") if l.strip()]
    dedup = [json.loads(l) for l in open(args.dedup, encoding="utf-8") if l.strip()]
    jev = Jev(key)
    t0 = time.monotonic()
    pre = run_prefilter(jev, emails)
    t1 = time.monotonic()
    dd = run_dedup(jev, dedup)
    t2 = time.monotonic()
    out = {"model": MODEL, "jev_calls": jev.calls, "jev_input_tokens": jev.input_tokens,
           "seconds": {"prefilter": round(t1 - t0, 1), "dedup": round(t2 - t1, 1)},
           "prefilter_raw": pre, "dedup_raw": dd}
    if args.claude:
        out["claude"] = run_claude(emails, dedup)
    Path(args.out).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out}: {jev.calls} Jev calls, {jev.input_tokens} input tokens")
    print(report(out, emails, dedup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
