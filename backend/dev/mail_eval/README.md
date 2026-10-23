# Jev vs Claude for three decisions in the email pipeline

`python dev/mail_eval.py [--claude]` re-runs everything here. It needs
`TYPESAFE_API_KEY`; `--claude` also needs `SMYLTE_ANTHROPIC_API_KEY` (and
`ANTHROPIC_WORKSPACE_ID` for a key that is not scoped to a workspace). Claude
is always `claude-haiku-5-5` — the production default — with a $2 cap.
`--report-only` re-prints the tables from a saved results file (an older file
is reported on the emails it covers).

## The data
`emails.jsonl` (190 emails, 95 actionable / 95 not, 42 in German) and
`dedup.jsonl` (98 duplicate-check cases: 37 new, 29 duplicate, 32 update) are
synthetic, written to a label by one model and re-labelled blind by another;
`clean` is true where the two agreed and neither called it borderline (147
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

## Titles, lists and what is not for the owner (since 2026-10-23)
The owner's next round of examples: titles that wrapped an assignment's name
in a verb and the class ("Complete assignment "4.2 - Anxiety Disorders" for DC
Psychology" for what they keep as "4.2 - Anxiety Disorders" in their DC
Psychology list), every task in the default list, school-wide announcements
(a signing day, a career fair) and meeting times still being traded. So:

- `new23`–`new34`, written and blind-labelled the same way, carry
  `gold_list` (a name from `mail_eval.OWNER_LISTS`, a fixed fictional owner's
  lists passed with every email, or `none`) and, for the tasks, `gold_title`.
  `--claude` reports lists right, exact titles and coursework titles that
  still start with a verb.
- Both models are now given the body the pipeline gives them, with quoted
  replies removed (`body_of`); until now they read the whole thread, so a reply
  whose only date sat in the quote it answered was scored on a date it never
  sees at home. 15 emails change.
- Relabelled: `sch-07` (a teacher offering two lesson slots), `sch-13` and
  `per23` (date polls) are not actionable — the owner wants nothing while a
  time is being agreed, only the email that sets it. For the same reason
  `per13` and `adv10`, replies confirming a time the owner proposed, are now
  events. `new30` (a proposed meeting date) was written as a reply task and is
  labelled not actionable; `new32` restates a task the owner already has,
  which only the pipeline's dedup can know, so as a single email it is a
  request.

The results below predate both rounds and were measured on the old labels.
The current prompt has not been run against Claude Haiku yet (both changes
were made without an Anthropic key). A dry run of the final prompt, with a
stronger model reading it as written and the labels above (with quoted replies
removed, as `body_of` does), decided actionable or not correctly for 146 of
the 147 clean emails and 187 of 190. The clean miss is `per6`, a note to self
written in its subject line alone: the pipeline settles a message with nothing
in its body without reading it, so the model never sees the subject (a known
gap; the parsed text cannot yet tell "never had a body" from "only a quote" or
"only an attachment"). The other two are `adv7`, a newsletter whose one
request is for a class the email does not say is the owner's, and `adv9`, a
bare "?". It routed all 12 rows with a `gold_list` as labelled (6 to a list, 6
to none), gave the exact title for all 7 with a `gold_title`, and put no date
in a title except ones that are part of the item's name ("2026/27", "Spring
2027"). That says the prompt reads as intended, not what Haiku will score.

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
Jev: ~250k input tokens (≈ $0.01). Claude Haiku 5.5 with the 2026-10-23
prompt, about 3k tokens of instructions per email, on 190 emails: roughly
0.9M input + ~50k output tokens (≈ $0.12), an estimate until the next run.
The 2026-10-05 run (Haiku 4.5, the old prompt, 156 emails) took ~370k input +
~40k output (≈ $0.57).
