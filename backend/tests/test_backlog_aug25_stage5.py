"""The 2026-08-25 sweep, stage 5: delivery infrastructure and test gaps.

Two findings, both of the same shape: a control exists, works, and has nothing
holding it in place. Neither is a bug — which is exactly why they sort last and
exactly why they are worth writing.

**NEITHER IS AN XFAIL PIN, and that is the finding rather than an omission.** A
test-gap whose subject turns out CORRECT is an ordinary passing test: marking one
`xfail(strict=True)` would XPASS and red the build the moment it ran. Every test
in this file was written and run before it was classified — the rule STAGES.md
records from the aug19 sweep, where three of four gaps came out ordinary and the
fourth found two live defects. Here both came out ordinary, and both subjects
were confirmed to fail under the regression they exist to catch (each test says
which mutation it was checked against).

So this file is a stage-5 section with no markers, sitting beside three stages
that carry them. Read it as the sweep's only closed-shaped work.

  * `scheduling.pad` widens the INSTANT rather than the wall clock, on the one
    unauthenticated write path into the owner's calendar, and the audit proved by
    mutation that reverting it to `Interval(iv.start - b, iv.end + b)` passes the
    ENTIRE backend suite. The DST battery in test_scheduling.py hardcodes
    `buffer_minutes=0` and the one non-zero-buffer test runs on an ordinary July
    Monday, so the two never meet.

  * `tasksd/access.py` is a security control with no test of any kind.
    `access_required` appears in the suite only as `False` inside settings
    fixtures; nothing constructs an `AccessVerifier`, nothing drives a token
    through it, and nothing pins the JWKS failure mode — which fails CLOSED today
    and is one sympathetic `return` away from turning Access into a no-op with
    the suite still green.

Eighteen tests, and every one was CONFIRMED AGAINST THE REGRESSION IT EXISTS TO
CATCH rather than merely observed to pass — a test written over correct code and
never seen red is a claim, not evidence. The four mutations, each applied alone
and reverted:

  * `pad` -> `Interval(iv.start - b, iv.end + b)` (the audit's own mutation,
    which passes the entire rest of the suite): fails both transition cases and
    the slot list.
  * `verify` -> `except PyJWKClientConnectionError: return` (the sympathetic
    "don't lock people out during an outage" change the finding names): fails
    `test_a_jwks_outage_fails_closed`.
  * the `access_required` guard in `create_app` disabled: fails all three
    startup cases.
  * `decode(..., options={"verify_aud": False, "verify_iss": False})` — the
    signature-alone verifier: fails the wrong-audience and wrong-issuer cases.

Radicale-free by construction: the scheduling half is pure slot math, and the
Access half serves a locally generated RSA key in place of a Cloudflare tenant,
so nothing here leaves the machine.
"""
from __future__ import annotations

import dataclasses
import json
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from tasksd import scheduling
from tasksd.access import AccessVerifier
from tasksd.app import create_app
from tasksd.config import Settings
from tasksd.scheduling import Interval
from tests.conftest import api_settings

pytestmark = [pytest.mark.backlog, pytest.mark.stage5]

TZ = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")

# The two transitions, in the zone test_scheduling.py already uses.
SPRING = date(2026, 3, 8)       # clocks jump 02:00 CST -> 03:00 CDT
FALL = date(2026, 11, 1)        # clocks repeat 01:00 CDT -> 01:00 CST


# ── GAP: buffer_minutes across a DST transition ────────────────────────────

def _busy(day: date, h: int, m: int, minutes: int) -> Interval:
    """A busy block expressed LOCALLY, which is how `busy_intervals` builds them
    and the only way the wall-clock regression is reachable."""
    start = datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)
    return Interval(start, start + timedelta(minutes=minutes))


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


@pytest.mark.parametrize("label, iv, buffer_minutes, expected", [
    # SPRING FORWARD. Busy 01:00-01:30 CST = 07:00Z-07:30Z. A two-hour buffer is
    # two hours of REAL time either side: 05:00Z .. 09:30Z. Under the wall-clock
    # version the end walks 01:30 -> 03:30 in naive fields and re-derives CDT, so
    # it lands at 08:30Z — an hour of the owner's declared buffer handed back as
    # bookable, on the one route an anonymous visitor can write through.
    ("spring-forward", (SPRING, 1, 0, 30), 120,
     ("2026-03-08T05:00:00+00:00", "2026-03-08T09:30:00+00:00")),
    # FALL BACK. Busy 01:00-01:30 in the FIRST pass of the repeated hour
    # (06:00Z-06:30Z; `datetime(…, tzinfo=TZ)` resolves the ambiguous clock time
    # to fold 0). Two hours either side is 04:00Z .. 08:30Z. The wall-clock
    # version ends at 09:30Z instead — over-blocking this time, which is the
    # safer direction and still wrong.
    ("fall-back", (FALL, 1, 0, 30), 120,
     ("2026-11-01T04:00:00+00:00", "2026-11-01T08:30:00+00:00")),
    # The same assertion where there is no transition to get wrong, so a failure
    # above cannot be blamed on the shape of the test. A week after the spring
    # forward the zone is CDT (UTC-5) all day, so 01:00 local is 06:00Z and the
    # padded bounds are 04:00Z .. 08:30Z — the two versions agree here, which is
    # the point.
    ("ordinary day", (date(2026, 3, 15), 1, 0, 30), 120,
     ("2026-03-15T04:00:00+00:00", "2026-03-15T08:30:00+00:00")),
])
def test_a_buffer_is_real_time_on_both_sides_of_a_transition(
    label, iv, buffer_minutes, expected
):
    """NOT an xfail: `pad` is already right and this is the test whose absence was
    the finding.

    `pad`'s own comment says it widens the instant — "Subtracting from an aware
    datetime adds to its naive fields and re-derives the offset, so a buffer
    straddling a transition would otherwise be an hour out" — and the audit
    proved by mutation that reverting it to

        Interval(iv.start - b, iv.end + b)

    passes the entire backend suite. `test_scheduling.py`'s DST batteries
    (`_dst_slots`, `_fall_back_slots`) hardcode `buffer_minutes=0`, and its only
    non-zero-buffer test runs on an ordinary July Monday, so the two halves never
    meet. This is the same shape as the already-closed "the DST slot battery
    never supplies busy intervals or a `now` inside the transition" gap, one
    field over — and that gap is why two slot-math defects survived three sweeps.

    Compared as INSTANTS, deliberately. Every datetime here shares one ZoneInfo
    object and CPython short-circuits `==` to a naive field comparison when
    `self.tzinfo is other.tzinfo`, so a local comparison cannot tell the two
    versions apart at all.

    CONFIRMED AGAINST THE REGRESSION rather than merely observed to pass: with
    `pad`'s body replaced by the wall-clock form above, spring-forward answers
    09:30Z -> 08:30Z and fall-back 08:30Z -> 09:30Z, and this test fails on both.
    """
    day, h, m, minutes = iv
    padded = scheduling.pad([_busy(day, h, m, minutes)], buffer_minutes)

    assert len(padded) == 1, f"{label}: {len(padded)} intervals, expected one"
    got = (_utc(padded[0].start), _utc(padded[0].end))
    assert got == expected, (
        f"{label}: a {buffer_minutes}-minute buffer around "
        f"{_utc(_busy(day, h, m, minutes).start)} produced {got[0]} .. {got[1]}, "
        f"which is not {buffer_minutes} minutes of real time either side"
    )


def test_the_buffer_a_spring_forward_slot_list_actually_honours():
    """The end-to-end half, on the route that matters.

    `book_slot` re-validates with the same function, so a slot this list offers
    is a slot an anonymous POST can put on the owner's calendar. Under the
    wall-clock regression this returns FIVE starts instead of three, and the two
    extra ones sit inside the two-hour buffer the owner declared.

    Availability Sunday 00:00-06:00 local on the spring-forward day is 06:00Z ..
    11:00Z (23 hours long, not 24). Busy 01:00-01:30 CST plus a two-hour buffer
    blocks through 09:30Z, leaving exactly three 30-minute slots.
    """
    av = scheduling.parse_availability({str(SPRING.weekday()): ["00:00-06:00"]})
    slots = scheduling.generate_slots(
        availability=av, duration_minutes=30,
        busy=[_busy(SPRING, 1, 0, 30)], buffer_minutes=120,
        tz=TZ, now=datetime(2026, 3, 7, 12, 0, tzinfo=UTC),
        min_notice_hours=0, horizon_days=2, only_day=SPRING,
    )
    assert [_utc(s.start) for s in slots] == [
        "2026-03-08T09:30:00+00:00",
        "2026-03-08T10:00:00+00:00",
        "2026-03-08T10:30:00+00:00",
    ], "a slot inside the owner's declared buffer was offered to an anonymous visitor"


# ── GAP: AccessVerifier and the access_required posture ────────────────────

TEAM = "example.cloudflareaccess.com"
AUD = "aud-under-test"
KID = "the-only-key"


@pytest.fixture(scope="module")
def signing_key():
    """A local RSA key. No Cloudflare tenant is involved anywhere in this file —
    the verifier's JWKS client is the only thing that would reach the network,
    and `_serve_jwks` stands in for it."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _settings(tmp_path, **overrides) -> Settings:
    # `Settings` is a frozen dataclass, so `replace` rather than assignment.
    fields = dict(access_required=True, access_team_domain=TEAM, access_aud=AUD)
    fields.update(overrides)
    return dataclasses.replace(api_settings(str(tmp_path / "access.db")), **fields)


def _serve_jwks(monkeypatch, key, *, kid: str = KID):
    """Answer the verifier's JWKS fetch with this key, and count the fetches."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid=kid, alg="RS256", use="sig")
    calls = {"n": 0}

    def _fetch(self):                       # noqa: ANN001 — patching PyJWT's own signature
        calls["n"] += 1
        return {"keys": [jwk]}

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", _fetch, raising=True)
    return calls


def _token(key, *, aud: str = AUD, iss: str = f"https://{TEAM}",
           exp_delta: int = 600, kid: str = KID, **claims) -> str:
    return jwt.encode(
        {"aud": aud, "iss": iss, "exp": int(time.time()) + exp_delta, **claims},
        key, algorithm="RS256", headers={"kid": kid},
    )


def test_access_off_is_a_total_no_op_even_for_a_hostile_header(tmp_path):
    """NOT an xfail: this is the test whose absence was the finding.

    `access_required` defaults to false and that is what production runs, so the
    off path is the one every deployment takes. It must not construct a JWKS
    client (there is no team domain to point one at) and must not look at the
    header at all — an `AccessVerifier` that tried to parse a garbage token with
    Access off would 403 every request on an ordinary install.
    """
    verifier = AccessVerifier(dataclasses.replace(
        api_settings(str(tmp_path / "off.db")), access_required=False))

    assert verifier._jwks is None, "a JWKS client was built with Access turned off"
    for token in (None, "", "garbage", "a.b.c"):
        verifier.verify(token)          # must not raise, must not fetch anything


def test_a_missing_assertion_header_is_a_401(tmp_path):
    """401 rather than 403: the credential is absent, not bad. `require_auth`
    surfaces this verbatim, and the distinction is what tells a Cloudflare tunnel
    misconfiguration ("no header arrived") from a rejected token."""
    verifier = AccessVerifier(_settings(tmp_path))
    for token in (None, ""):
        with pytest.raises(HTTPException) as e:
            verifier.verify(token)
        assert e.value.status_code == 401, token
        assert "Cf-Access-Jwt-Assertion" in str(e.value.detail)


def test_a_valid_assertion_passes(tmp_path, signing_key, monkeypatch):
    """The positive control, and it is what makes every refusal below mean
    something: a suite where the verifier rejected EVERYTHING would satisfy all
    of them and brick the app."""
    _serve_jwks(monkeypatch, signing_key)
    AccessVerifier(_settings(tmp_path)).verify(_token(signing_key))


@pytest.mark.parametrize("label, kw", [
    ("wrong audience", dict(aud="someone-elses-app")),
    ("wrong issuer", dict(iss="https://attacker.cloudflareaccess.com")),
    ("expired", dict(exp_delta=-60)),
])
def test_a_token_that_is_not_ours_is_a_403(label, kw, tmp_path, signing_key, monkeypatch):
    """Signed by the right key and still refused. `aud` and `iss` are what tie an
    assertion to THIS application and THIS Cloudflare team — a verifier that
    checked the signature alone would accept any token the same tenant issued for
    any other app behind the same Access instance."""
    _serve_jwks(monkeypatch, signing_key)
    verifier = AccessVerifier(_settings(tmp_path))

    with pytest.raises(HTTPException) as e:
        verifier.verify(_token(signing_key, **kw))
    assert e.value.status_code == 403, label


@pytest.mark.parametrize("label, token", [
    ("not a JWT at all", "garbage"),
    ("three segments of nothing", "a.b.c"),
    # `alg: none` is the classic JWT downgrade: a token with a header saying it
    # needs no signature and an empty signature segment. `AccessVerifier` pins
    # `algorithms=["RS256"]`, but the refusal happens earlier still — the JWKS
    # client cannot find a signing key for it.
    ("alg=none", jwt.encode({"aud": AUD, "iss": f"https://{TEAM}"}, key=None, algorithm="none")),
])
def test_an_unsigned_or_unparseable_token_is_a_403(
    label, token, tmp_path, signing_key, monkeypatch
):
    _serve_jwks(monkeypatch, signing_key)
    verifier = AccessVerifier(_settings(tmp_path))

    with pytest.raises(HTTPException) as e:
        verifier.verify(token)
    assert e.value.status_code == 403, label


def test_a_jwks_outage_fails_closed(tmp_path, signing_key, monkeypatch):
    """The one the finding calls out by name, and the reason this gap is worth
    more than its severity suggests.

    It fails closed today — `except Exception -> 403` catches
    `PyJWKClientConnectionError` along with everything else — but nothing pinned
    it. The failure mode the gap permits is sympathetic and plausible: someone
    "fixes" a lockout during a Cloudflare outage by returning early when the
    fetch raises. Every /api request then passes the Access gate with any token
    at all, or none, and `pytest -q` stays green.

    Driven with a VALID token, deliberately: a bad token would 403 for its own
    reasons and the test would pass whatever the outage branch did.
    """
    good = _token(signing_key)
    _serve_jwks(monkeypatch, signing_key)
    AccessVerifier(_settings(tmp_path)).verify(good)     # the same token passes when JWKS is up

    def _boom(self):                        # noqa: ANN001 — patching PyJWT's own signature
        raise jwt.exceptions.PyJWKClientConnectionError("cannot reach the JWKS endpoint")

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", _boom, raising=True)

    with pytest.raises(HTTPException) as e:
        AccessVerifier(_settings(tmp_path)).verify(good)
    assert e.value.status_code == 403, (
        "the JWKS endpoint was unreachable and the request was let through — "
        "Access is a no-op for as long as the outage lasts"
    )


@pytest.mark.parametrize("label, missing", [
    ("no team domain", dict(access_team_domain="")),
    ("no audience", dict(access_aud="")),
    ("neither", dict(access_team_domain="", access_aud="")),
])
def test_access_required_without_its_configuration_refuses_to_start(
    label, missing, tmp_path
):
    """The THIRD fail-closed refusal in `create_app`, beside the two
    `test_security.py` already covers.

    That file's section header says why they are tested at all: "a refactor that
    reordered the password fallback, or dropped the well-known-default
    comparison, would have left the whole suite green with the gate gone." The
    Access refusal is the same argument — turning the edge gate on and getting a
    running server that enforces nothing is strictly worse than not starting.
    """
    with pytest.raises(RuntimeError, match="refusing to start unprotected"):
        create_app(_settings(tmp_path, **missing))


def test_access_required_with_its_configuration_does_start(tmp_path):
    """CONTROL. The refusal must fire only when the configuration is INCOMPLETE;
    a correctly configured Access deployment has to boot. `create_app` touches no
    network, and `AccessVerifier.__init__` only constructs a `PyJWKClient`, which
    does not fetch until it is asked for a key."""
    assert create_app(_settings(tmp_path))
