"""Address and domain normalisation."""
from __future__ import annotations

import pytest

from smylted.mail.addresses import (
    aligned,
    is_self,
    matches,
    matches_any,
    normalize_address,
    normalize_domain,
    normalize_pattern,
    noreply_local_part,
    valid_pattern,
)


def test_unicode_domain_uses_uts46_non_transitional():
    # IDNA 2003 (the stdlib codec) maps ß to "ss": straße.de would compare
    # equal to strasse.de, a different registrant.
    assert normalize_domain("straße.de") == "xn--strae-oqa.de"
    assert normalize_domain("STRASSE.de") == "strasse.de"
    assert normalize_address("info@straße.de") == "info@xn--strae-oqa.de"
    assert normalize_pattern("*.straße.de") == "*.xn--strae-oqa.de"


def test_unicode_domain_and_its_ace_form_compare_equal():
    assert normalize_domain("bücher.example") == "xn--bcher-kva.example"
    assert normalize_domain("Bücher.Example.") == "xn--bcher-kva.example"
    assert normalize_domain("xn--bcher-kva.example") == "xn--bcher-kva.example"


@pytest.mark.parametrize("domain,expected", [
    ("school.org", "school.org"),
    ("Mail.School.ORG.", "mail.school.org"),
    ("ab--cd.example", "ab--cd.example"),
    ("mailin008.protonmail.ch", "mailin008.protonmail.ch"),
    ("localhost", None),
    ("a..b", None),
    ("-a.example", None),
    ("_dmarc.school.org", None),
    ("x" * 64 + ".example", None),
    ("", None),
])
def test_ascii_domains(domain, expected):
    assert normalize_domain(domain) == expected


@pytest.mark.parametrize("domain", ["a‍؀.example", "͸.example", "a b.example"])
def test_unencodable_domains_are_refused(domain):
    assert normalize_domain(domain) is None


def test_matches_exact_address_case_insensitively():
    addr = normalize_address("Office@School.Example")
    assert matches(addr, normalize_pattern("office@school.example"))
    assert not matches(addr, normalize_pattern("other@school.example"))


def test_bare_domain_matches_that_domain_only():
    assert matches("office@school.example", "school.example")
    assert not matches("office@news.school.example", "school.example")


def test_wildcard_matches_strict_subdomains_only():
    assert matches("office@news.school.example", "*.school.example")
    assert matches("office@a.b.school.example", "*.school.example")
    assert not matches("office@school.example", "*.school.example")


def test_lookalike_suffix_does_not_match():
    assert not matches("office@evilschool.example", "school.example")
    assert not matches("office@evilschool.example", "*.school.example")


def test_matches_any_returns_the_matching_pattern():
    patterns = ["office@other.example", "*.school.example", "school.example"]
    assert matches_any("office@school.example", patterns) == "school.example"
    assert matches_any("office@news.school.example", patterns) == "*.school.example"
    assert matches_any("office@else.example", patterns) is None
    assert matches_any(None, patterns) is None


def test_plus_tag_of_a_self_address_is_self():
    own = ["me@proton.me"]
    assert is_self("me@proton.me", own)
    assert is_self("me+school@proton.me", own)
    assert not is_self("you@proton.me", own)
    assert not is_self(None, own)


@pytest.mark.parametrize("addr,expected", [
    ("no-reply@school.example", True),
    ("noreply@school.example", True),
    ("do-not-reply@school.example", True),
    ("donotreply@school.example", True),
    ("reply@school.example", False),
    ("info@school.example", False),
])
def test_noreply_local_part(addr, expected):
    assert noreply_local_part(addr) is expected


def test_aligned():
    assert aligned("school.example", "school.example")
    assert aligned("bounce.school.example", "school.example")
    assert aligned("school.example", "bounce.school.example")
    assert not aligned("school.example", "other.example")
    assert not aligned("evilschool.example", "school.example")


@pytest.mark.parametrize("pattern", ["", "*.", "a@b@c"])
def test_invalid_patterns_are_refused(pattern):
    assert normalize_pattern(pattern) is None
    assert valid_pattern(pattern) is False
