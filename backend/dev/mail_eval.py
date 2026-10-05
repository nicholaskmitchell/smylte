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


def run_dedup(jev: Jev, cases: list[dict]) -> list[dict]:
    NONE = "none of them: different work from every candidate"

    def one(c):
        cands = c["candidates"]
        state = {"new_item": {"title": c["new_item"]["title"], "notes": c["new_item"]["notes"],
                              "due": c["new_item"]["due"]},
                 "candidates": {x["id"]: {"title": x["title"], "notes": x["notes"], "due": x["due"]} for x in cands}}
        instr = ("Which item in `candidates` is the same piece of work as `new_item`? The same piece of "
                 "work means the same action on the same thing for the same period; a different month of a "
                 "recurring bill, or a different action on the same thing, is different work.")
        fwd = {x["id"]: _item_text(x) for x in cands}
        fwd["none"] = NONE
        rev = {"none": NONE}
        rev.update({x["id"]: _item_text(x) for x in reversed(cands)})
        qs = {"match_a": {"type": "choice", "instructions": instr, "criteria": fwd},
              "match_b": {"type": "choice", "instructions": instr, "criteria": rev}}
        for x in cands:
            cid = x["id"]
            qs[f"same_{cid}"] = {"type": "noul",
                                 "instructions": f"Is `new_item` the same piece of work as `candidates.{cid}` (the same action on the same thing for the same period)?"}
            qs[f"adds_{cid}"] = {"type": "noul",
                                 "instructions": f"Does `new_item` add details that `candidates.{cid}` does not have, such as a changed amount, place, time or a new requirement? Ignore the due dates."}
        a = jev.ask(state, qs)
        ma, mb = a["match_a"], a["match_b"]
        probs = {k: (ma["probabilities"].get(k, 0) + mb["probabilities"].get(k, 0)) / 2 for k in fwd}
        same = {x["id"]: a[f"same_{x['id']}"]["noul"] for x in cands}
        adds = {x["id"]: a[f"adds_{x['id']}"]["noul"] for x in cands}
        return {"id": c["id"], "choice_a": ma["choice"], "choice_b": mb["choice"],
                "conf": min(ma["confidence"], mb["confidence"]) if ma["choice"] == mb["choice"] else 0.0,
                "probs": probs, "same": same, "adds": adds}
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(one, cases))


def decide_dedup(c: dict, r: dict, *, variant: str, same_t: float = 0.5, adds_t: float = 0.5,
                 conf_t: float = 0.0) -> tuple[str, str | None, bool]:
    """(label, target, confident) from Jev's answers plus code for the dates."""
    if variant == "choice":
        best = max(r["probs"], key=r["probs"].get)
        confident = r["choice_a"] == r["choice_b"] and r["conf"] >= conf_t
        target = None if best == "none" else best
    else:  # nouls
        cid, p = max(r["same"].items(), key=lambda kv: kv[1]) if r["same"] else (None, 0.0)
        target = cid if p >= same_t else None
        confident = abs(p - 0.5) * 2 >= conf_t
    if target is None:
        return "new", None, confident
    cand = next(x for x in c["candidates"] if x["id"] == target)
    new_due, old_due = c["new_item"]["due"], cand.get("due")
    if new_due and new_due != old_due:
        return "update", target, confident
    if r["adds"].get(target, 0.0) >= adds_t:
        return "update", target, confident
    return "duplicate", target, confident


# ── optional Claude baseline through the production client ───────────────────
def run_claude(emails: list[dict], dedup: list[dict]) -> dict | None:
    key = _key("SMYLTE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    if not key:
        return None
    sys.path.insert(0, str(HERE.parent))
    from smylted.mail.llm import Candidate, EmailForExtraction, Extraction, LlmClient  # noqa: E402
    model = os.environ.get("SMYLTE_MAIL_MODEL", "claude-haiku-4-5")
    llm = LlmClient(api_key_provider=lambda: key, model_provider=lambda: model)
    out = {"model": model, "extract": {}, "match": {}}
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


# ── metrics ──────────────────────────────────────────────────────────────────
def prefilter_metrics(cases, results, field):
    by = {r["id"]: r for r in results}
    act = [c for c in cases if c["gold"] == "actionable"]
    non = [c for c in cases if c["gold"] == "not_actionable"]
    rows = []
    for t in (0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5):
        dropped = [c["id"] for c in act if by[c["id"]][field] < t]
        skipped = [c for c in non if by[c["id"]][field] < t]
        rows.append({"skip_below": t, "actionable_dropped": len(dropped), "dropped_ids": dropped,
                     "non_actionable_skipped": len(skipped),
                     "skip_rate": round(len(skipped) / max(1, len(non)), 3)})
    return {"n_actionable": len(act), "n_non_actionable": len(non), "thresholds": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emails", default=str(HERE / "mail_eval" / "emails.jsonl"))
    ap.add_argument("--dedup", default=str(HERE / "mail_eval" / "dedup.jsonl"))
    ap.add_argument("--out", default=str(HERE / "mail_eval" / "results.json"))
    ap.add_argument("--claude", action="store_true")
    args = ap.parse_args()
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
