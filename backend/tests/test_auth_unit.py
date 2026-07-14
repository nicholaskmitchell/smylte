"""Auth-layer unit tests: limiter keying and credential-check edge cases.
(RateLimiter's window/lockout behavior is covered in test_scheduling.py.)"""
from __future__ import annotations

import pytest

from tasksd.app import _EVENT_STATUS, _TASK_STATUS, _check_status
from tasksd.auth import Authenticator, hash_password, limiter_key


def test_limiter_key_collapses_ipv6_to_its_64():
    # A /64 is one customer allocation: rotating inside it shares one counter.
    a = limiter_key("2001:db8:abcd:12:aaaa::1")
    b = limiter_key("2001:db8:abcd:12:bbbb:cccc:dddd:2")
    c = limiter_key("2001:db8:abcd:13::1")   # different /64 → different key
    assert a == b == "2001:db8:abcd:12::/64"
    assert c != a


def test_limiter_key_ipv4_mapped_and_plain():
    assert limiter_key("203.0.113.9") == "203.0.113.9"
    # ::ffff:a.b.c.d is an IPv4 client in disguise — it must key as that IPv4,
    # not lump every mapped client (and ::1) into one ::/64 bucket.
    assert limiter_key("::ffff:203.0.113.9") == "203.0.113.9"
    assert limiter_key("::1") != limiter_key("::ffff:203.0.113.9")
    assert limiter_key("unknown") == "unknown"   # unparseable keys on itself


def test_check_credentials_non_ascii_is_a_clean_reject():
    auth = Authenticator(
        user="admin", password_hash=hash_password("pw"), secret="s" * 32, ttl_s=60
    )
    # compare_digest raises TypeError on non-ASCII str; this must be a False,
    # not a 500 that also skips lockout accounting.
    assert auth.check_credentials("ádmin", "pw") is False
    assert auth.check_credentials("admin", "ﬁsh") is False
    assert auth.check_credentials("admin", "pw") is True


def test_check_status_validates_the_rfc_vocabulary():
    assert _check_status("completed", _TASK_STATUS) == "COMPLETED"
    assert _check_status(" tentative ", _EVENT_STATUS) == "TENTATIVE"
    assert _check_status(None, _TASK_STATUS) is None
    for bad, allowed in (("BOGUS", _TASK_STATUS), ("COMPLETED", _EVENT_STATUS)):
        with pytest.raises(Exception) as e:
            _check_status(bad, allowed)
        assert getattr(e.value, "status_code", None) == 422
