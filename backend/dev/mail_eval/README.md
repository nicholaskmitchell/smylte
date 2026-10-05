# Jev vs Claude for three decisions in the email pipeline

`python dev/mail_eval.py [--claude]` re-runs everything here. It needs
`TYPESAFE_API_KEY`; `--claude` also needs `SMYLTE_ANTHROPIC_API_KEY` (and
`ANTHROPIC_WORKSPACE_ID` for a key that is not scoped to a workspace). Claude
is always `claude-haiku-4-5` — the production default — with a $2 cap.
`--report-only` re-prints the tables from a saved results file.

## The data
`emails.jsonl` (156 emails, 78 actionable / 78 not, 40 in German) and
`dedup.jsonl` (98 duplicate-check cases: 37 new, 29 duplicate, 32 update) are
synthetic, written to a label by one model and re-labelled blind by another;
`clean` is true where the two agreed and neither called it borderline (121
emails, 95 dedup cases). Every domain is fictional. It is a stand-in for the
owner's mail, not a sample of it — the numbers say which design is safer, not
what accuracy to expect at home.

## Results (2026-10-05, jev-1.13.0 and claude-haiku-4-5)

**Pre-filter — not adopted.** Skipping the extraction call when Jev's
p(actionable) < 0.05 dropped no real request and skipped 16 of 78 non-actionable
emails; at < 0.1 it started dropping real ones (`per20`, a group email naming
the owner as owing a deposit, sat at 0.06). It removed none of the junk
suggestions Claude makes — those are the request-shaped emails both models
find ambiguous. So it is ~10% fewer Haiku calls (a fraction of a cent each)
bought with a thin margin against the one failure a filter must not have.

**Task or event — Jev when confident, else Claude.** On 66 clean actionable
emails: Jev alone 61–62, Claude alone 62–63, Jev at confidence ≥ 0.7 with
Claude deciding the rest 65 (both runs). `jev.MIN_CONFIDENCE` is 0.7.
Production sends Jev the same state as `email_state` (sender with name,
subject, sent date, body), so the threshold describes what runs.

**Duplicate check — Jev, Claude when unsure.** Raw accuracy is a wash (Claude
alone 91–93 of 98, Jev with Claude in the 0.35–0.65 band 92), but the errors
are not alike:

| | new work merged into another task | extra suggestion (duplicate missed) | update read as duplicate / vice versa |
|---|---|---|---|
| Claude alone (two runs) | **4 and 4** | 0 | 3 and 1 |
| Jev, Claude when unsure | **0** | 1 | 5 |

A merge is a request the owner never sees; the others are a suggestion to
dismiss. Jev answers only "is this the same piece of work as candidate N?"
(one Noul per candidate) and, for the best match, "does `new` change anything
about `existing`?" (a Choice asked in both option orders). Whether the
deadline moved is compared in code.

What did not work, kept here so nobody tries it again: asking "does
`new_item` add details not in `candidates.C1`?" inside the full candidate
list. Jev fired on plain rewordings (0.5–0.9) — the indirection its docs warn
about — and the only threshold that rescued it (0.9) collapsed at 0.95.

## Cost of one full run
Jev: ~250k input tokens (≈ $0.01). Claude Haiku: ~370k input + ~40k output
tokens (≈ $0.57).
