"""Task-or-event rules: parsing, the canonical form, refusal on save, and decide()."""
from __future__ import annotations

from dataclasses import replace

import pytest

from smylted.mail import kindrules as K
from smylted.mail.kindrules import Condition, KindFacts, decide, parse_rule


def _facts(**kw) -> KindFacts:
    base = dict(sender="office@school.example", subject="Parent evening on Thursday",
                body="Dear parents,\nthe parent\n evening starts at 18:00.", model_kind="task",
                has_time=False, has_date=False, has_location=False)
    base.update(kw)
    return KindFacts(**base)


def test_parse_rule_fields_and_canonical_form():
    r = parse_rule('  FROM:*.School.Example  Subject:"Parent Evening"   =>   EVENT ')
    assert r.kind == "event"
    assert r.conditions == (Condition("from", "*.school.example", False),
                            Condition("subject", "parent evening", False))
    assert r.source == 'from:*.school.example subject:"parent evening" -> event'
    assert parse_rule(r.source) == r          # canonical text parses back to itself

    assert parse_rule("subject:invoice ->task").source == "subject:invoice -> task"
    assert parse_rule("model:Event has:TIME -> event").source == "model:event has:time -> event"
    assert parse_rule("body:Rechnung -> task").conditions[0].value == "rechnung"


def test_negation():
    r = parse_rule("has:time -from:news.example -> event")
    assert r.conditions[1] == Condition("from", "news.example", True)
    assert r.source == "has:time -from:news.example -> event"


def test_quoting_and_escapes():
    r = parse_rule(r'subject:"say \"hi\" \\ now" -> task')
    assert r.conditions[0].value == 'say "hi" \\ now'
    assert r.source == r'subject:"say \"hi\" \\ now" -> task'
    assert parse_rule(r.source) == r
    # A single word that was quoted is written bare; one with a quote stays quoted.
    assert parse_rule('subject:"invoice" -> task').source == "subject:invoice -> task"
    assert parse_rule(r'subject:"a\"b" -> task').source == r'subject:"a\"b" -> task'


@pytest.mark.parametrize("line, problem", [
    ("subject:invoice", "-> task"),
    ("-> task", "at least one condition"),
    ("subject:invoice -> meeting", "not task or event"),
    ("subject:a -> task -> event", "-> task"),
    ("has:time -event:x -> event", "unknown field"),
    ("invoice -> task", "not a condition"),
    ("from:not_a_domain -> task", "not an address"),
    ("has:weekday -> event", "time, date or location"),
    ("model:maybe -> event", "task or event"),
    ('subject:"unclosed -> task', "not closed"),
    ('subject:ab"c" -> task', "quoted phrase"),
    ('subject:"a"b -> task', "quoted phrase"),
    ('subject:"  " -> task', "needs a value"),
    ("subject:" + "x" * 201 + " -> task", "200"),
    (" ".join(f"subject:w{i}" for i in range(11)) + " -> task", "10 conditions"),
    ("subject:" + "x" * 495 + " -> task", "500"),
])
def test_bad_rules_are_refused_with_their_number(line, problem):
    with pytest.raises(ValueError, match=problem):
        parse_rule(line)
    with pytest.raises(ValueError) as exc:
        K.check_rules(["# my rules", "", "subject:ok -> task", line])
    assert str(exc.value).startswith("rule 3: ")   # blank lines are not counted
    assert problem in str(exc.value)


def test_check_rules_drops_blanks_and_comments():
    assert K.check_rules(["", "  # note", "Subject:Invoice -> Task", "   "]) == [
        "subject:invoice -> task"]
    assert K.check_rules([]) == []


def test_check_rules_limits_the_count():
    lines = [f"subject:w{i} -> task" for i in range(K.MAX_RULES)]
    assert len(K.check_rules(lines)) == K.MAX_RULES
    with pytest.raises(ValueError, match=f"rule {K.MAX_RULES + 1}: "):
        K.check_rules([*lines, "subject:one-more -> task"])


def test_load_rules_skips_bad_lines():
    rules = K.load_rules(["subject:a -> task", "garbage", "# c", "", 7, "has:time -> event"])
    assert [r.source for r in rules] == ["subject:a -> task", "has:time -> event"]


def test_decide_model_mode():
    rules = K.load_rules(["subject:parent -> task"])
    assert decide("model", rules, _facts(model_kind="event")) == ("event", "the model chose event")
    assert decide("model", rules, _facts(model_kind="task")) == ("task", "the model chose task")
    assert decide("something else", rules, _facts(model_kind="event"))[0] == "event"
    # "jev" is decided by the pipeline; here it falls back to the model's choice.
    assert decide("jev", rules, _facts(model_kind="event")) == ("event", "the model chose event")


def test_decide_rules_mode_first_match_wins():
    rules = K.load_rules([
        "-from:*.school.example -> task",
        'from:*.school.example subject:"parent evening" -> event',
        "subject:parent -> task",
    ])
    f = _facts(sender="office@mail.school.example")
    assert decide("rules", rules, f) == (
        "event", 'rule: from:*.school.example subject:"parent evening" -> event')
    # The apex is not covered by *.domain, so the negated first rule matches.
    assert decide("rules", rules, replace(f, sender="a@school.example"))[0] == "task"
    assert decide("rules", [], f) == ("task", "no rule matched")
    assert decide("rules", K.load_rules(["subject:nothing -> event"]), f) == ("task", "no rule matched")


def test_decide_body_matches_across_wrapped_lines():
    rules = K.load_rules(['body:"PARENT EVENING" -> event'])
    assert decide("rules", rules, _facts(sender=None))[0] == "event"


def test_decide_has_and_model_facts():
    rules = K.load_rules(["model:event has:time -> event", "has:date -has:location -> event",
                          "model:event -> event"])
    assert decide("rules", rules, _facts(model_kind="event", has_time=True)) == (
        "event", "rule: model:event has:time -> event")
    assert decide("rules", rules, _facts(has_date=True)) == (
        "event", "rule: has:date -has:location -> event")
    assert decide("rules", rules, _facts(has_date=True, has_location=True)) == (
        "task", "no rule matched")
    assert decide("rules", rules, _facts(model_kind="event")) == (
        "event", "rule: model:event -> event")
    assert decide("rules", K.load_rules(["from:school.example -> event"]), _facts(sender=None)) == (
        "task", "no rule matched")
