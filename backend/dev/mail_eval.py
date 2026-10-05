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
and match calls — so the two can be compared on one machine. TYPESAFE_API_KEY
(or SMYLTE_TYPESAFE_API_KEY) is required for the Jev half.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")

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


def email_state(c: dict) -> dict:
    return {"email": {"from": f"{c['from_name']} <{c['from_addr']}>", "subject": c["subject"],
                      "sent": c["sent"], "body": c["body"][:8000]}}


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
    from smylted.mail.llm import Candidate, EmailForExtraction, Extraction, LlmClient  # noqa: E402
    # Haiku only, deliberately not configurable here: this is a cost-bounded
    # comparison against the production default, not a model sweep.
    model = "claude-haiku-4-5"
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
    headers = {"anthropic-workspace-id": workspace} if workspace else None
    spent = {"in": 0, "out": 0}

    def factory(*_a):
        client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com",
                                     default_headers=headers, max_retries=2, timeout=60.0)
        create = client.messages.create

        def counted(**kw):
            # Hard stop well under $2 at Haiku 4.5's $1 / $5 per Mtok.
            if spent["in"] / 1e6 * 1.0 + spent["out"] / 1e6 * 5.0 > 2.0:
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
    for c in emails:
        sent = datetime.fromisoformat(c["sent"]) if c.get("sent") else None
        try:
            ex = llm.extract(EmailForExtraction(sender_name=c["from_name"], sender_addr=c["from_addr"],
                                                subject=c["subject"], sent=sent, body=c["body"][:8000]))
            out["extract"][c["id"]] = {"actionable": ex.is_actionable, "kind": ex.kind}
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
    lines = []
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
