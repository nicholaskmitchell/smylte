"""Authentication-Results parsing and the sender verdict built on it.

Header blocks are written out literally, the way Proton's inbound MTA stamps
them (one header per method, authserv-id `mailinNNN.protonmail.ch`), so the
tests read like the mail they stand for.
"""
from __future__ import annotations

import email
import email.policy

from smylted.mail import authres
from smylted.mail.authres import DEFAULT_TRUSTED, parse_header, verify_sender

PROTON = "mailin008.protonmail.ch"


def _msg(*headers: str, from_: str = "Office <office@school.org>"):
    block = "".join(h.rstrip("\n") + "\n" for h in headers)
    raw = f"{block}From: {from_}\nSubject: test\n\nbody\n"
    return email.message_from_string(raw, policy=email.policy.default)


def _ar(text: str, server: str = PROTON) -> str:
    return f"Authentication-Results: {server};\n {text}"


def _proton(dmarc: str = "dmarc=pass (p=quarantine dis=none) header.from=school.org") -> list[str]:
    return [
        _ar("arc=none"),
        _ar("dkim=pass (Good 2048 bit rsa-sha256 signature) header.d=school.org\n"
            " header.i=@school.org header.a=rsa-sha256"),
        _ar("spf=pass smtp.mailfrom=school.org"),
        _ar(dmarc),
    ]


def _verify(msg, addr="office@school.org", count=1, trusted=DEFAULT_TRUSTED):
    return verify_sender(msg, addr, count, trusted)


def test_proton_block_passes_via_dmarc():
    v = _verify(_msg(*_proton()))
    assert v.passed is True
    assert v.method == "dmarc"
    assert v.reason == f"dmarc=pass header.from=school.org ({PROTON})"


def test_dmarc_fail_wins_over_dkim_and_spf_passes():
    v = _verify(_msg(*_proton("dmarc=fail (p=none dis=none) header.from=school.org")))
    assert v.passed is False
    assert v.method == "dmarc"
    assert v.reason == "dmarc=fail"


def test_forged_pass_lower_down_cannot_outvote_protons_fail():
    forged = "Authentication-Results: mail.protonmail.ch; dmarc=pass header.from=school.org"
    msg = _msg(*_proton("dmarc=fail (p=none dis=none) header.from=school.org"), forged)
    assert _verify(msg).passed is False


def test_untrusted_server_only():
    msg = _msg("Authentication-Results: mx.evil.example; dmarc=pass header.from=school.org")
    v = _verify(msg)
    assert v.passed is False
    assert v.reason == "no Authentication-Results from a trusted server"


def test_dmarc_none_aligned_dkim_subdomain_passes():
    msg = _msg(_ar("dmarc=none header.from=school.org"),
               _ar("dkim=pass header.d=mail.school.org"))
    v = _verify(msg)
    assert v.passed is True
    assert v.method == "dkim"
    assert v.reason == f"dkim=pass header.d=mail.school.org aligned with school.org ({PROTON})"


def test_dmarc_none_unaligned_dkim_aligned_spf_passes_via_spf():
    msg = _msg(_ar("dmarc=none header.from=school.org"),
               _ar("dkim=pass header.d=other.org"),
               _ar("spf=pass smtp.mailfrom=bounce@em.school.org"))
    v = _verify(msg)
    assert v.passed is True
    assert v.method == "spf"
    assert "em.school.org" in v.reason


def test_dmarc_none_softfail_spf_no_dkim_fails():
    msg = _msg(_ar("dmarc=none header.from=school.org"),
               _ar("spf=softfail smtp.mailfrom=school.org"))
    v = _verify(msg)
    assert v.passed is False
    assert v.method is None
    assert v.reason == "no DMARC pass and no SPF or DKIM pass aligned with school.org"


def test_dkim_signing_domain_from_header_i():
    msg = _msg(_ar("dkim=pass header.i=@school.org"))
    v = _verify(msg)
    assert v.passed is True and v.method == "dkim"


def test_two_from_addresses_fail():
    msg = _msg(*_proton(), from_="office@school.org, other@evil.example")
    v = _verify(msg, count=2)
    assert v.passed is False
    assert v.reason == "the From header must name exactly one address"
    assert _verify(_msg(*_proton()), addr=None).passed is False


def test_dmarc_pass_for_another_domain_fails():
    v = _verify(_msg(*_proton("dmarc=pass header.from=other.org")))
    assert v.passed is False
    assert v.reason == "dmarc pass is for a different domain than From"


def test_arc_authentication_results_are_never_read():
    msg = _msg("ARC-Authentication-Results: i=1; mail.protonmail.ch; dmarc=pass header.from=school.org")
    assert authres.collect(msg) == []
    v = _verify(msg)
    assert v.passed is False
    assert v.reason == "no Authentication-Results from a trusted server"


def test_parse_header_comments_quotes_none_versions_folding():
    h = parse_header("mx.example.com 1; spf=pass smtp.mailfrom=a.org")
    assert h.authserv_id == "mx.example.com"
    assert h.results == (authres.MethodResult("spf", "pass", {"smtp.mailfrom": "a.org"}),)

    h = parse_header("MX.Example.COM;\r\n\tdkim/1=PASS (outer (nested) still comment)\n"
                     ' header.D=School.org reason="signature ok; (not a comment)"')
    assert h.authserv_id == "mx.example.com"
    (r,) = h.results
    assert r.method == "dkim" and r.result == "pass"
    assert r.props == {"header.d": "School.org", "reason": "signature ok; (not a comment)"}

    h = parse_header("mx.example.com; none")
    assert h.authserv_id == "mx.example.com" and h.results == ()

    assert parse_header("") is None
    assert parse_header("  ; spf=pass") is None


def test_strip_comments():
    assert authres.strip_comments('a (b (c) d) e "x (y)" f') == 'a   e "x (y)" f'
    assert authres.strip_comments(r"a (b \) c) d") == "a   d"
    assert authres.strip_comments("a (unclosed d") == "a "


def test_authserv_ids_distinct_in_order():
    msg = _msg(*_proton(), "Authentication-Results: mx.evil.example; dmarc=pass",
               _ar("arc=none"))
    assert authres.authserv_ids(msg) == [PROTON, "mx.evil.example"]


def test_trusted_list_exact_vs_wildcard():
    parsed = [parse_header("mail.example; spf=pass"), parse_header("mx.mail.example; spf=pass")]
    assert [h.authserv_id for h in authres.trusted_only(parsed, ["mail.example"])] == ["mail.example"]
    assert [h.authserv_id for h in authres.trusted_only(parsed, ["*.mail.example"])] == ["mx.mail.example"]
    assert authres.trusted_only(parsed, ["someone@mail.example", "not a domain"]) == []


def test_forged_dkim_pass_below_protons_dkim_none_fails():
    # A domain with no DMARC record, spoofed: Proton records dmarc=none,
    # dkim=none and a softfail, and the sender wrote a dkim=pass of its own
    # under a trusted-looking id further down.
    msg = _msg(_ar("dmarc=none (p=none dis=none) header.from=school.org"),
               _ar("spf=softfail smtp.mailfrom=evil.example"),
               _ar("dkim=none"),
               _ar("arc=none"),
               "Received: from mx.evil.example by mailin008.protonmail.ch",
               _ar("dkim=pass header.d=school.org", server="mailin001.protonmail.ch"))
    v = _verify(msg)
    assert v.passed is False
    assert v.reason == "no DMARC pass and no SPF or DKIM pass aligned with school.org"


def test_forged_spf_pass_below_protons_spf_pass_for_another_domain_fails():
    msg = _msg(_ar("dmarc=none (p=none dis=none) header.from=school.org"),
               _ar("spf=pass smtp.mailfrom=bounce@evil.example"),
               _ar("dkim=none"),
               _ar("spf=pass smtp.mailfrom=school.org", server="mailin001.protonmail.ch"))
    assert _verify(msg).passed is False


def test_protons_own_dkim_pass_on_top_passes():
    msg = _msg(_ar("dmarc=none header.from=school.org"),
               _ar("dkim=pass header.d=school.org"),
               _ar("dkim=none", server="mailin001.protonmail.ch"))
    v = _verify(msg)
    assert v.passed is True and v.method == "dkim"
    assert v.reason == f"dkim=pass header.d=school.org aligned with school.org ({PROTON})"


def test_protons_own_spf_pass_on_top_passes():
    msg = _msg(_ar("dmarc=none header.from=school.org"),
               _ar("spf=pass smtp.mailfrom=school.org"),
               _ar("spf=fail smtp.mailfrom=school.org", server="mailin001.protonmail.ch"))
    v = _verify(msg)
    assert v.passed is True and v.method == "spf"
