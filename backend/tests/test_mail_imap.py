"""IMAP client — modified UTF-7, LIST parsing, and real TLS over loopback.

The connection tests run `smylted.mail.imap` against `tests/imap_server.py`, a
small threaded IMAP server on 127.0.0.1 with a freshly generated self-signed
certificate (the shape Bridge uses). What they pin down is the order of
events a fake cannot show: the certificate is checked before LOGIN is sent,
only EXAMINE and BODY.PEEK reach the server, and a server that echoes the
password back does not get it into an error or a log line.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pytest

from smylted.mail import imap, redact
from smylted.mail.imap import (
    FolderInfo,
    ImapConfig,
    MailConnectError,
    cert_fingerprint_pem,
    connect,
    decode_mutf7,
    encode_mutf7,
    parse_list_response,
    probe_fingerprint,
    quote_mailbox,
)
from tests.imap_server import free_port, make_self_signed_cert, run_server

USER = "owner@example.org"
PASSWORD = 'bridge"pass\\Q7w9e2'       # a quote and a backslash: imaplib quotes, the server unquotes

UTC = timezone.utc
MSG1 = b"From: a@school.example\r\nSubject: one\r\nAuthentication-Results: mx.example; dkim=pass\r\n\r\nfirst\r\n"
MSG3 = b"From: b@example.com\r\nSubject: three\r\n\r\nthird\r\n"
MSG7 = b"From: c@example.com\r\nSubject: seven\r\n\r\n" + b"x" * 4000 + b"\r\n"
DATE1 = datetime(2026, 9, 1, 8, 30, 0, tzinfo=UTC)
DATE3 = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
DATE7 = datetime(2026, 10, 4, 18, 15, 5, tzinfo=timezone(timedelta(hours=-5)))


@pytest.fixture(scope="module")
def cert():
    return make_self_signed_cert()


@pytest.fixture
def mailboxes():
    return {
        "INBOX": {"flags": [], "uidvalidity": 1234,
                  "messages": {1: (MSG1, DATE1), 3: (MSG3, DATE3), 7: (MSG7, DATE7)}},
        "Sent": {"flags": ["\\Sent"], "uidvalidity": 5, "messages": {}},
        "All Mail": {"flags": ["\\All"], "uidvalidity": 6, "messages": {}},
        "Labels/School": {"flags": [], "uidvalidity": 7, "messages": {}},
        "Entw&APw-rfe": {"flags": ["\\Drafts"], "uidvalidity": 8, "messages": {}},
    }


@pytest.fixture(autouse=True)
def _redaction():
    redact.install_log_redaction()
    redact.forget_all_for_tests()
    yield
    redact.forget_all_for_tests()


def _server(cert, mailboxes, tls_mode="starttls", **kw):
    cert_pem, key_pem = cert
    return run_server(mailboxes=mailboxes, user=USER, password=PASSWORD, tls_mode=tls_mode,
                      cert_pem=cert_pem, key_pem=key_pem, **kw)


def _cfg(host, port, *, tls="starttls", cert_mode="pinned", pem="", user=USER):
    return ImapConfig(host=host, port=port, username=user, tls=tls, cert_mode=cert_mode,
                      pinned_cert_pem=pem, timeout=5.0)


def _verbs(server) -> list[str]:
    """The command word of every line the server received (`UID FETCH` as one)."""
    out = []
    for line in server.commands:
        parts = line.split()
        if len(parts) < 2:
            continue
        verb = parts[1].upper()
        if verb == "UID" and len(parts) > 2:
            verb += " " + parts[2].upper()
        out.append(verb)
    return out


# --- modified UTF-7 ------------------------------------------------------------

@pytest.mark.parametrize("name", ["Entwürfe", "&", "日本語", "Labels/Ünïcode & more",
                                  "INBOX", "a&b/ü&ö", "😀 emoji"])
def test_mutf7_round_trips(name):
    wire = encode_mutf7(name)
    assert wire.isascii()
    assert decode_mutf7(wire) == name


def test_mutf7_known_vectors():
    assert encode_mutf7("Entwürfe") == "Entw&APw-rfe"
    assert encode_mutf7("&") == "&-"
    assert encode_mutf7("日本語") == "&ZeVnLIqe-"
    # RFC 3501 §5.1.3's own example.
    assert decode_mutf7("~peter/mail/&U,BTFw-/&ZeVnLIqe-") == "~peter/mail/台北/日本語"


def test_mutf7_malformed_is_a_value_error():
    with pytest.raises(ValueError):
        decode_mutf7("&ZeVn")
    with pytest.raises(ValueError):
        decode_mutf7("&*!-")


def test_quote_mailbox_escapes():
    assert quote_mailbox('a "b" \\c') == '"a \\"b\\" \\\\c"'


# --- LIST parsing --------------------------------------------------------------

def test_parse_list_response_shapes():
    data = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
        b'(\\Noselect \\HasChildren) NIL "Folders"',
        b'(\\HasNoChildren) "/" Archive',
        (b'(\\HasNoChildren \\All) "/" {8}', b"All Mail"),
        b"",
        b'(\\HasNoChildren) "/" "Entw&APw-rfe"',
        b'(\\HasNoChildren) "\\\\" "Quote \\"me\\""',
        b"garbage that is not a LIST line",
    ]
    got = parse_list_response(data)
    assert [f.name for f in got] == ["INBOX", "Sent Items", "Folders", "Archive", "All Mail",
                                     "Entwürfe", 'Quote "me"']
    by = {f.name: f for f in got}
    assert by["Sent Items"].flags == frozenset({"\\hasnochildren", "\\sent"})
    assert by["Folders"].delimiter is None
    assert by["INBOX"].delimiter == "/"
    assert by['Quote "me"'].delimiter == "\\"
    assert by["All Mail"].flags == frozenset({"\\hasnochildren", "\\all"})
    assert by["Entwürfe"].raw == "Entw&APw-rfe"


# --- certificates ----------------------------------------------------------------

def test_cert_fingerprint_pem(cert):
    fp = cert_fingerprint_pem(cert[0])
    assert len(fp.split(":")) == 32 and fp == fp.upper()
    with pytest.raises(ValueError):
        cert_fingerprint_pem("not a certificate")
    with pytest.raises(ValueError):
        cert_fingerprint_pem("-----BEGIN CERTIFICATE-----\n!!!\n-----END CERTIFICATE-----")


def test_build_ssl_context_modes():
    system = imap.build_ssl_context(_cfg("h", 1, cert_mode="system"))
    assert system.verify_mode.name == "CERT_REQUIRED" and system.check_hostname
    pinned = imap.build_ssl_context(_cfg("h", 1, cert_mode="pinned"))
    assert pinned.verify_mode.name == "CERT_NONE" and not pinned.check_hostname
    for ctx in (system, pinned):
        assert ctx.minimum_version >= imap.ssl.TLSVersion.TLSv1_2


# --- real protocol ---------------------------------------------------------------

def test_starttls_pinned_reads_without_changing_anything(cert, mailboxes):
    with _server(cert, mailboxes) as server:
        host, port = server
        src = connect(_cfg(host, port, pem=cert[0]), PASSWORD)
        try:
            folders = {f.name: f for f in src.list_folders()}
            assert set(folders) == {"INBOX", "Sent", "All Mail", "Labels/School", "Entwürfe"}
            assert "\\sent" in folders["Sent"].flags
            assert "\\all" in folders["All Mail"].flags
            assert folders["Labels/School"].delimiter == "/"

            state = src.select(folders["INBOX"])
            assert (state.uidvalidity, state.uidnext, state.exists) == (1234, 8, 3)

            assert src.search_uids() == [1, 3, 7]
            assert src.search_uids(after_uid=1) == [3, 7]
            # `8:*` makes the server return 7 (the highest UID); the client drops it.
            assert src.search_uids(after_uid=7) == []
            assert src.search_uids(since=date(2026, 9, 20)) == [3, 7]
            assert src.search_uids(after_uid=3, since=date(2026, 9, 1)) == [7]

            got = list(src.fetch([7, 1, 3, 99], max_bytes=1_000_000))
            assert [m.uid for m in got] == [1, 3, 7]          # ascending; 99 never existed
            assert [m.raw for m in got] == [MSG1, MSG3, MSG7]
            assert [m.size for m in got] == [len(MSG1), len(MSG3), len(MSG7)]
            assert [m.internaldate for m in got] == [DATE1, DATE3, DATE7]
            assert all(m.internaldate.tzinfo is not None for m in got)

            small = {m.uid: m for m in src.fetch([1, 3, 7], max_bytes=1000)}
            assert small[7].raw is None and small[7].size == len(MSG7)
            assert small[1].raw == MSG1

            hdr = src.fetch_header_fields(1, ["AUTHENTICATION-RESULTS"])
            assert hdr.startswith(b"Authentication-Results: mx.example; dkim=pass")
        finally:
            src.close()
            src.close()                                       # idempotent

        verbs = _verbs(server)
        assert "EXAMINE" in verbs and "LOGIN" in verbs
        assert any("BODY.PEEK[]" in c for c in server.commands)
        assert "SELECT" not in verbs
        assert not any("STORE" in v for v in verbs)
        assert server.seen == {}
        # STARTTLS came before the password.
        assert verbs.index("STARTTLS") < verbs.index("LOGIN")


def test_implicit_tls_pinned_works(cert, mailboxes):
    with _server(cert, mailboxes, tls_mode="ssl") as (host, port):
        src = connect(_cfg(host, port, tls="ssl", pem=cert[0]), PASSWORD)
        try:
            assert "INBOX" in {f.name for f in src.list_folders()}
        finally:
            src.close()


def test_pin_mismatch_refuses_before_login(cert, mailboxes):
    other_pem, _ = make_self_signed_cert()
    with _server(cert, mailboxes) as server:
        host, port = server
        with pytest.raises(MailConnectError) as ei:
            connect(_cfg(host, port, pem=other_pem), PASSWORD)
    err = ei.value
    assert err.kind == "tls"
    assert cert_fingerprint_pem(cert[0]) in str(err)
    assert cert_fingerprint_pem(other_pem) in str(err)
    assert err.fingerprint == cert_fingerprint_pem(cert[0])
    assert "LOGIN" not in _verbs(server)


def test_system_mode_on_self_signed_reports_the_fingerprint(cert, mailboxes):
    with _server(cert, mailboxes) as server:
        host, port = server
        with pytest.raises(MailConnectError) as ei:
            connect(_cfg(host, port, cert_mode="system"), PASSWORD)
    err = ei.value
    assert err.kind == "tls"
    assert "self-signed" in str(err)
    assert err.fingerprint == cert_fingerprint_pem(cert[0])
    assert err.fingerprint in str(err)
    assert "LOGIN" not in _verbs(server)


def test_insecure_localhost_only_on_loopback(cert, mailboxes, monkeypatch, caplog):
    monkeypatch.setattr(imap, "_insecure_warned", False)
    caplog.set_level(logging.WARNING, logger="smylted.mail")
    with _server(cert, mailboxes) as (host, port):
        src = connect(_cfg(host, port, cert_mode="insecure_localhost"), PASSWORD)
        src.close()
    assert "certificate checks are OFF" in caplog.text

    port = free_port()
    with pytest.raises(MailConnectError) as ei:
        connect(_cfg("example.com", port, cert_mode="insecure_localhost"), PASSWORD)
    assert ei.value.kind == "config"                  # refused before any socket was opened
    assert "loopback" in str(ei.value)


def test_config_errors_before_any_network():
    port = free_port()
    cases = [
        (_cfg("127.0.0.1", port, tls="plain"), PASSWORD),
        (_cfg("127.0.0.1", port, cert_mode="trust-me"), PASSWORD),
        (_cfg("127.0.0.1", port, pem=""), PASSWORD),
        (_cfg("127.0.0.1", port, cert_mode="system", user=""), PASSWORD),
        (_cfg("127.0.0.1", port, cert_mode="system"), ""),
    ]
    for cfg, password in cases:
        with pytest.raises(MailConnectError) as ei:
            connect(cfg, password)
        assert ei.value.kind == "config", str(ei.value)


def test_wrong_password_is_never_echoed(cert, mailboxes, caplog):
    wrong = "wrong-Bridge-pass-5309"
    redact.register_secret(wrong)
    caplog.set_level(logging.DEBUG)
    with _server(cert, mailboxes, echo_password_on_failure=True) as server:
        host, port = server
        with pytest.raises(MailConnectError) as ei:
            connect(_cfg(host, port, pem=cert[0]), wrong)
    assert "LOGIN" in _verbs(server)
    err = ei.value
    assert err.kind == "auth"
    assert wrong not in str(err)
    assert redact.REDACTED in str(err)                 # the server did echo it
    assert err.__cause__ is None and err.__suppress_context__
    fmt = logging.Formatter()
    assert wrong not in caplog.text
    assert not any(wrong in fmt.format(r) for r in caplog.records)


def test_server_without_starttls(cert, mailboxes):
    with _server(cert, mailboxes, tls_mode="none_offered") as server:
        host, port = server
        with pytest.raises(MailConnectError) as ei:
            connect(_cfg(host, port, pem=cert[0]), PASSWORD)
    assert ei.value.kind == "tls"
    assert "STARTTLS" in str(ei.value)
    assert "LOGIN" not in _verbs(server)


def test_nothing_listening_is_a_network_error():
    port = free_port()
    with pytest.raises(MailConnectError) as ei:
        connect(_cfg("127.0.0.1", port, cert_mode="system"), PASSWORD)
    assert ei.value.kind == "network"
    assert f"127.0.0.1:{port}" in str(ei.value)


@pytest.mark.parametrize("tls_mode", ["starttls", "ssl"])
def test_probe_fingerprint_never_logs_in(cert, mailboxes, tls_mode):
    with _server(cert, mailboxes, tls_mode=tls_mode) as server:
        host, port = server
        fp = probe_fingerprint(_cfg(host, port, tls=tls_mode, cert_mode="system"))
    assert fp == cert_fingerprint_pem(cert[0])
    assert "LOGIN" not in _verbs(server)


def test_probe_fingerprint_none_when_unreachable():
    assert probe_fingerprint(_cfg("127.0.0.1", free_port(), cert_mode="system")) is None


def test_select_unknown_folder_is_a_protocol_error(cert, mailboxes):
    with _server(cert, mailboxes) as (host, port):
        src = connect(_cfg(host, port, pem=cert[0]), PASSWORD)
        try:
            with pytest.raises(MailConnectError) as ei:
                src.select(FolderInfo(name="Nope", raw="Nope", flags=frozenset(), delimiter="/"))
        finally:
            src.close()
    assert ei.value.kind == "protocol"
