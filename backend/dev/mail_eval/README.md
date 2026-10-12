# Jev vs Claude for three decisions in the email pipeline

`python dev/mail_eval.py [--claude]` re-runs everything here. It needs
`TYPESAFE_API_KEY`; `--claude` also needs `SMYLTE_ANTHROPIC_API_KEY` (and
`ANTHROPIC_WORKSPACE_ID` for a key that is not scoped to a workspace). Claude
is always `claude-haiku-5-5` — the production default — with a $2 cap.
`--report-only` re-prints the tables from a saved results file (an older file
is reported on the emails it covers).

## The data
`emails.jsonl` (178 emails, 88 actionable / 90 not, 42 in German) and
`dedup.jsonl` (98 duplicate-check cases: 37 new, 29 duplicate, 32 update) are
synthetic, written to a label by one model and re-labelled blind by another;
`clean` is true where the two agreed and neither called it borderline (137
emails, 95 dedup cases). Every domain is fictional. It is a stand-in for the
owner's mail, not a sample of it — the numbers say which design is safer, not
what accuracy to expect at home.

## What counts as actionable (since 2026-10-12)
The owner wants fewer, better suggestions: coursework, work and business
deadlines, appointments, official and household matters — not notices about
their own accounts. Their examples: "save your files" after cancelling an
office suite, and "Update payment information" after a subscription's card
was declined. The labels follow that standard now:

- Relabelled, each with the old label in `relabel`: `com7` (a streaming
  plan's declined card) and `com9` ("was this you?" sign-in check) are
  account notices, not actionable; `com18` (a failed delivery that is retried
  automatically) is delivery news; `per16`, `adv20` and `de17` (invitations
  with a reply date) are tasks to reply by that date, not events; `sch-24` (a
  confirmed volunteer slot) is an event, like `com11`.
- `new1`–`new22` are written and blind-labelled the same way: the owner's two
  examples in fictional form, other account notices, learning-platform,
  professor and registrar mail, an RSVP by a date, business invoices, a failed
  domain renewal that would take the owner's business site down, a returned
  insurance premium, cold outreach and a vendor's launch party. The tasks
  among them and the three relabelled RSVP tasks carry `gold_due`, which the
  report checks; the new rows also carry `gold_title_hint`, an ideal title
  for a reader, which nothing scores.
- The extraction now names a category, and only coursework, work, personal,
  appointment, official and errand mail becomes a suggestion (see `llm.py`,
  `pipeline.py`). `--claude` reports requests the category dropped (`gated`),
  titles that still carry a date, due mismatches, and actionable mail from
  no-reply senders, which the bulk filter drops before any model reads it.

The results below predate this and were measured on the old labels. The new
prompt has not been run against Claude Haiku yet (the change was made without
an Anthropic key). A dry run with a stronger model reading the prompt as
written, on 177 of the 178 emails, decided actionable or not correctly for
every clean one and 173 of all; it put no date in any title, matched every
`gold_due`, and chose the right kind for 70 of 71 clean actionable emails.
That says the prompt reads as intended, not what Haiku will score.

## Results (2026-10-05, jev-1.13.0 and claude-haiku-4-5, old labels)

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
Jev: ~250k input tokens (≈ $0.01). Claude Haiku 5.5 with the 2026-10-12
prompt, which is about 1.5k tokens longer: roughly 0.7M input + ~45k output
tokens (≈ $0.10), an estimate until the next run. The 2026-10-05 run (Haiku
4.5, the old prompt, 156 emails) took ~370k input + ~40k output (≈ $0.57).
