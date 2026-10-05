"""The mail configuration: tolerant load, strict checkers, folder and host rules."""
from __future__ import annotations

import hashlib
import ssl
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from smylted.mail import settings as S
from smylted.mail.settings import MailConfig


def _self_signed_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_load_defaults():
    assert S.load({}) == MailConfig()
    assert S.load(None) == MailConfig()
    assert S.load("not a mapping") == MailConfig()
    assert S.FIELDS[0] == "enabled" and S.FIELDS[-2:] == ("kind_decider", "kind_rules")
    assert set(S.public(MailConfig())) == set(S.FIELDS)


def test_load_good_values():
    cfg = S.load({
        "enabled": True, "model": " claude-sonnet-4-5 ", "imap_host": "[::1]",
        "imap_port": 993, "imap_tls": "ssl", "imap_cert_mode": "pinned",
        "folders": ["inbox", "Labels/School"], "self_addresses": ["Me@Proton.ME"],
        "always_parse": ["*.School.org"], "never_parse": ["news.example"],
        "capture_notes_to_self": False, "poll_minutes": 1440, "body_max_chars": 500,
        "backfill_days": 0, "task_list": "school", "event_calendar": "family",
        "trusted_authserv_ids": ["mx.example.org"], "auto_accept_min_confidence": 1,
        "kind_decider": "rules", "kind_rules": ["Subject:Invoice => TASK"],
    })
    assert cfg.enabled is True
    assert cfg.model == "claude-sonnet-4-5"
    assert cfg.imap_host == "::1"
    assert (cfg.imap_port, cfg.imap_tls, cfg.imap_cert_mode) == (993, "ssl", "pinned")
    assert cfg.folders == ("INBOX", "Labels/School")
    assert cfg.self_addresses == ("me@proton.me",)
    assert cfg.always_parse == ("*.school.org",)
    assert cfg.never_parse == ("news.example",)
    assert cfg.capture_notes_to_self is False
    assert (cfg.poll_minutes, cfg.body_max_chars, cfg.backfill_days) == (1440, 500, 0)
    assert (cfg.task_list, cfg.event_calendar) == ("school", "family")
    assert cfg.trusted_authserv_ids == ("mx.example.org",)
    assert cfg.auto_accept_min_confidence == 1.0
    assert cfg.kind_decider == "rules"
    assert cfg.kind_rules == ("subject:invoice -> task",)
    pub = S.public(cfg)
    assert pub["folders"] == ["INBOX", "Labels/School"] and isinstance(pub["kind_rules"], list)


def test_load_bad_values_fall_back_per_field():
    d = MailConfig()
    cfg = S.load({
        "enabled": "yes", "model": "bad model!", "imap_host": "a b", "imap_port": True,
        "imap_username": "a\nb", "imap_tls": "tls", "imap_cert_mode": "none",
        "imap_pinned_cert": "junk", "folders": "INBOX",
        "self_addresses": ["ok@school.org", "not-an-address", 7, "OK@school.org"],
        "always_parse": ["school.org", "@@", ""], "never_parse": None,
        "capture_notes_to_self": 0, "poll_minutes": 0, "body_max_chars": 100001,
        "backfill_days": 91.0, "task_list": "", "event_calendar": 3,
        "trusted_authserv_ids": ["someone@protonmail.ch", "*.protonmail.ch"],
        "auto_accept_min_confidence": True, "kind_decider": "script",
        "kind_rules": ["subject:x -> task", "nope -> task", "# comment", "has:time -> event"],
    })
    assert cfg.enabled is d.enabled
    assert cfg.model == d.model
    assert cfg.imap_host == d.imap_host
    assert cfg.imap_port == d.imap_port
    assert cfg.imap_username == d.imap_username
    assert (cfg.imap_tls, cfg.imap_cert_mode, cfg.imap_pinned_cert) == ("starttls", "system", "")
    assert cfg.folders == ("INBOX",)
    assert cfg.self_addresses == ("ok@school.org",)
    assert cfg.always_parse == ("school.org",)
    assert cfg.never_parse == ()
    assert cfg.capture_notes_to_self is True
    assert (cfg.poll_minutes, cfg.body_max_chars, cfg.backfill_days) == (5, 8000, 7)
    assert (cfg.task_list, cfg.event_calendar) == (None, None)
    assert cfg.trusted_authserv_ids == ("*.protonmail.ch",)
    assert cfg.auto_accept_min_confidence is None
    assert cfg.kind_decider == "model"
    assert cfg.kind_rules == ("subject:x -> task", "has:time -> event")
    for bad in (-0.1, 1.5, float("nan"), "0.5"):
        assert S.load({"auto_accept_min_confidence": bad}).auto_accept_min_confidence is None
    assert S.load({"folders": []}).folders == ()


def test_check_model_host_username():
    assert S.check_model(" claude-haiku-4-5 ") == "claude-haiku-4-5"
    assert S.check_model("org/model:v1@2") == "org/model:v1@2"
    for bad in ("", "-x", "a b", "x" * 101):
        with pytest.raises(ValueError, match="claude-haiku-4-5"):
            S.check_model(bad)
    assert S.check_host(" bridge.local ") == "bridge.local"
    assert S.check_host("[::1]") == "::1"
    assert S.check_host("127.0.0.1") == "127.0.0.1"
    for bad in ("", "a b", "a/b", "me@host", "[nope]", "x" * 254):
        with pytest.raises(ValueError, match="hostname or IP address"):
            S.check_host(bad)
    assert S.check_username(" me@proton.me ") == "me@proton.me"
    for bad in ("a\r\nb", "x" * 321):
        with pytest.raises(ValueError, match="username"):
            S.check_username(bad)


def test_check_lists_name_the_bad_entry():
    assert S.check_folders([" inbox ", "", "INBOX", "Labels/School"]) == ["INBOX", "Labels/School"]
    assert S.check_folders([]) == []
    with pytest.raises(ValueError, match="'a\\\\nb'"):
        S.check_folders(["a\nb"])
    with pytest.raises(ValueError, match="50"):
        S.check_folders([f"f{i}" for i in range(51)])

    assert S.check_addresses(["Me@Proton.me", "me@proton.me"]) == ["me@proton.me"]
    with pytest.raises(ValueError, match="'nobody' is not an email address"):
        S.check_addresses(["ok@x.org", "nobody"])

    assert S.check_patterns(["School.org", "*.school.org", "a@b.org"]) == [
        "school.org", "*.school.org", "a@b.org"]
    with pytest.raises(ValueError, match=r"'\*\.' is not an address, a domain, or \*\.domain"):
        S.check_patterns(["*."])

    assert S.check_authserv_patterns(["protonmail.ch", "*.protonmail.ch"]) == [
        "protonmail.ch", "*.protonmail.ch"]
    with pytest.raises(ValueError, match="'me@protonmail.ch'"):
        S.check_authserv_patterns(["me@protonmail.ch"])
    with pytest.raises(ValueError, match="20"):
        S.check_authserv_patterns([f"s{i}.example.org" for i in range(21)])

    assert S.check_kind_rules(["subject:x -> task"]) == ["subject:x -> task"]
    with pytest.raises(ValueError, match="rule 1"):
        S.check_kind_rules(["bad"])


def test_check_pem_and_fingerprint():
    pem = _self_signed_pem()
    assert S.check_pem("") == ""
    norm = S.check_pem("some text before\r\n" + pem.replace("\n", "\r\n") + "\ntrailing")
    assert norm == pem.strip() + "\n"
    der = ssl.PEM_cert_to_DER_cert(norm)
    hexd = hashlib.sha256(der).hexdigest().upper()
    assert S.pem_fingerprint(pem) == ":".join(hexd[i:i + 2] for i in range(0, 64, 2))

    junk = "-----BEGIN CERTIFICATE-----\nnot base64 at all!!\n-----END CERTIFICATE-----"
    for bad in ("junk", junk, pem + pem, "x" * 20001):
        with pytest.raises(ValueError, match="not a PEM certificate"):
            S.check_pem(bad)
    assert S.pem_fingerprint("") is None
    assert S.pem_fingerprint(junk) is None


def test_hard_excluded_folders():
    for name in ("Sent", "Drafts", "All Mail", "Spam", "Trash"):
        assert S.is_hard_excluded(name), name
    assert S.is_hard_excluded("[Gmail]/Sent Mail", (), "/")
    for flag in ("\\Sent", "\\All", "\\Junk"):
        assert S.is_hard_excluded("Whatever", {flag}), flag
    for name in ("INBOX", "Labels/School", "Folders/Receipts", "Archive"):
        assert not S.is_hard_excluded(name, {"\\HasNoChildren"}, "/"), name


def test_folder_selected():
    assert S.folder_selected("inbox", ["INBOX"])
    assert S.folder_selected("INBOX", ["Inbox"])
    assert S.folder_selected("Labels/X", ["Labels/X"])
    assert not S.folder_selected("labels/x", ["Labels/X"])
    assert not S.folder_selected("INBOX", [])


def test_is_loopback_host():
    for host in ("localhost", "LocalHost", "127.0.0.1", "127.5.5.5", "::1", "[::1]"):
        assert S.is_loopback_host(host), host
    for host in ("192.168.1.2", "example.com", ""):
        assert not S.is_loopback_host(host), host


def test_utcnow_iso_shape():
    ts = S.utcnow_iso()
    assert len(ts) == 24 and ts.endswith("Z") and ts[10] == "T"
