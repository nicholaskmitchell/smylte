"""Message parsing: the facts the pipeline reads, from real-shaped .eml files."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from smylted.mail import message
from smylted.mail.message import (
    html_to_text,
    ledger_key,
    normalize_body,
    normalize_message_id,
    parse_id_list,
    parse_message,
    strip_quotes,
    thread_id,
    header_value,
)

CORPUS = Path(__file__).parent / "corpus" / "mail"


def load(name: str) -> bytes:
    return (CORPUS / name).read_bytes()


def parsed(name: str):
    return parse_message(load(name))


def test_plain_request_every_field():
    m = parsed("msg_plain_request.eml")
    assert m.message_id == "req-001@school.example"
    assert m.from_name == "Ms Smith"
    assert m.from_addr == "office@school.example"
    assert m.from_count == 1
    assert m.to == ("me@proton.me", "parents@club.example")
    assert m.cc == ("coach@club.example", "me@proton.me")
    assert m.subject == "Permission slip for the museum trip"
    assert m.date == datetime(2026, 10, 5, 9, 30, tzinfo=timezone(timedelta(hours=2)))
    assert m.references == ("root-001@school.example", "req-000@school.example")
    assert m.in_reply_to == "req-000@school.example"
    assert m.text.startswith("Hello,\n\nPlease sign and return the permission slip")
    assert m.text.rstrip().endswith("Ms Smith")
    assert m.html_used is False
    assert m.calendars == ()
    assert m.headers.get("Message-ID") == "<req-001@school.example>"
    assert header_value(m, "subject") == "Permission slip for the museum trip"
    assert header_value(m, "X-Not-There") is None


def test_html_only_is_rendered_and_scripts_dropped():
    m = parsed("msg_html_only.eml")
    assert m.html_used is True
    assert m.text == (
        "Hello & welcome.\n"
        "First line\nsecond line\n"
        "- Bring a packed lunch\n"
        "- Wear sturdy shoes\n"
        "Details at the trip page (https://school.example/trip)."
    )
    assert "alert" not in m.text and "color" not in m.text and "Trip\n" not in m.text


@pytest.mark.parametrize("name", [
    "msg_gmail_reply.eml",
    "msg_apple_reply.eml",
    "msg_thunderbird_reply.eml",
])
def test_html_replies_keep_only_the_new_text(name):
    m = parsed(name)
    assert m.html_used is True
    assert m.text in ("Yes, I can bring the nets on Thursday.", "Kick-off is at 14:00.")
    assert "wrote" not in m.text and "nets on Thursday?" not in m.text


def test_outlook_reply_header_and_everything_after_is_dropped():
    m = parsed("msg_outlook_reply.eml")
    assert m.text == "Thursday at 18:00 works for us."


def test_html_to_text_details():
    assert html_to_text("<p>a</p><p>b</p>") == "a\nb"
    assert html_to_text("<div>x<br><br>y</div>") == "x\n\ny"
    assert html_to_text("<a href='https://a.example/'>https://a.example</a>") == "https://a.example"
    assert html_to_text("<a href='mailto:x@y.example'>mail</a>") == "mail"
    assert html_to_text("<table><tr><td>a</td><td>b</td></tr></table>") == "a b"
    assert html_to_text("<pre>  keep\n  this</pre>").splitlines() == ["keep", "this"]
    # A quote container with text after it keeps that following text.
    assert html_to_text("<div>new</div><blockquote type='cite'>old</blockquote><div>tail</div>") == "new\ntail"
    assert html_to_text("") == ""
    assert html_to_text("<!-- c --><p>x</p>") == "x"


def test_html_to_text_falls_back_to_tag_stripping(monkeypatch):
    import lxml.html

    def boom(*a, **k):
        raise ValueError("no")

    monkeypatch.setattr(lxml.html, "document_fromstring", boom)
    assert html_to_text("<b>bold</b> text") == "bold text"


@pytest.mark.parametrize("text,expected", [
    ("Thanks, will do.\n> old line\n> older line\n", "Thanks, will do."),
    ("Yes.\n\nOn Mon, 5 Oct 2026 at 09:00, Ms Smith <office@school.example> wrote:\n> Can you?\n",
     "Yes."),
    ("Yes.\n\nOn Mon, 5 Oct 2026 at 09:00, Ms Smith <office@school.example>\nwrote:\n> Can you?\n",
     "Yes."),
    ("Ja.\n\nAm 05.10.2026 um 09:00 schrieb Frau Müller <office@school.example>:\n> Kannst du?\n",
     "Ja."),
    ("Sure.\n\n-----Original Message-----\nFrom: A\nSent: x\n\nold text\n", "Sure."),
    ("Sure.\n\n----- Ursprüngliche Nachricht -----\nold text\n", "Sure."),
    ("Sure.\n\nFrom: Ms Smith <office@school.example>\nSent: Monday, October 5, 2026 9:00 AM\n"
     "To: Nick\nSubject: Parent evening\n\nold text\n", "Sure."),
    ("Sure.\n________________________________\nFrom: Ms Smith\nold text\n", "Sure."),
    ("Sure.\n________________________________\n\nNothing to see\n",
     "Sure.\n________________________________\n\nNothing to see"),
])
def test_strip_quotes_cuts(text, expected):
    assert strip_quotes(text) == expected


def test_strip_quotes_keeps_forwarded_content():
    fwd = (
        "Please add this to my list.\n\n"
        "---------- Forwarded message ---------\n"
        "From: Ms Smith <office@school.example>\n"
        "Date: Mon, 5 Oct 2026 at 09:00\n"
        "Subject: Permission slip\n"
        "To: <me@proton.me>\n\n"
        "Sign the slip by Friday.\n"
    )
    assert strip_quotes(fwd) == fwd.strip()


def test_strip_quotes_leaves_unquoted_text_alone():
    assert strip_quotes("Line one.\r\n\r\n\r\n\r\nLine two.   \r\n") == "Line one.\n\nLine two."
    assert strip_quotes("On the agenda: nothing.\nFrom: me") == "On the agenda: nothing.\nFrom: me"


@pytest.mark.parametrize("text", [
    "On 10/5/26 9:00 AM, Ms Smith wrote:\n> Can you bring the nets on Thursday?\n>\n> Thanks\n\n"
    "Yes, I will bring the nets.\n",
    "On Mon, 5 Oct 2026 at 09:00, Ms Smith <office@school.example>\nwrote:\n> Can you bring the nets?\n\n"
    "Yes, I will bring the nets.\n",
    "Am 05.10.2026 um 09:00 schrieb Frau Müller <office@school.example>:\n> Kannst du die Netze mitbringen?\n\n"
    "Yes, I will bring the nets.\n",
], ids=["thunderbird", "two-line", "german"])
def test_strip_quotes_keeps_a_bottom_posted_reply(text):
    assert strip_quotes(text) == "Yes, I will bring the nets."


def test_strip_quotes_keeps_every_inline_answer():
    text = (
        "On Mon, Oct 5, 2026 at 9:00 AM Owner <me@proton.me> wrote:\n"
        "> Can I pick up the books on Thursday?\n\n"
        "Thursday does not work. Please come on Friday at 3pm and bring the signed form.\n\n"
        "> And do you need the form?\n\n"
        "Yes, signed by both parents.\n"
    )
    assert strip_quotes(text) == (
        "Thursday does not work. Please come on Friday at 3pm and bring the signed form.\n\n"
        "Yes, signed by both parents."
    )


@pytest.mark.parametrize("text,subject,expected", [
    ("Am Freitag kann ich nicht.\nAm 05.10.2026 um 10:00 schrieb Coach <c@x>:\n> Kommst du Freitag?\n",
     "AW: Training", "Am Freitag kann ich nicht."),
    ("On Friday I can't.\nOn Mon, Oct 5, 2026 at 10:00 AM Coach <c@x> wrote:\n> Are you coming Friday?\n",
     "Re: Training", "On Friday I can't."),
], ids=["german", "english"])
def test_a_one_line_top_post_above_an_attribution_is_kept(text, subject, expected):
    # The line above the attribution starts like one ("Am …", "On …"), but the
    # attribution is complete on its own line, so it is not a wrapped one.
    assert strip_quotes(text, subject=subject) == expected


OUTLOOK_FW_PLAIN = (
    "Can you handle this one?\n\n"
    "________________________________\n"
    "From: Grundschule Office <office@school.example>\n"
    "Sent: Monday, October 5, 2026 9:00 AM\n"
    "To: Partner <partner@example.com>\n"
    "Subject: Field trip\n\n"
    "Please sign the field trip permission slip and return it by Friday.\n"
)
OUTLOOK_FW_PLAIN_DE = (
    "Kannst du das übernehmen?\n\n"
    "________________________________\n"
    "Von: Grundschule Office <office@school.example>\n"
    "Gesendet: Montag, 5. Oktober 2026 09:00\n"
    "An: Partner <partner@example.com>\n"
    "Betreff: Ausflug\n\n"
    "Bitte die Einverständniserklärung bis Freitag unterschreiben.\n"
)


@pytest.mark.parametrize("text,subject", [
    (OUTLOOK_FW_PLAIN, "FW: Field trip"),
    (OUTLOOK_FW_PLAIN, "Fwd: Field trip"),
    (OUTLOOK_FW_PLAIN, "  fw : Field trip"),
    (OUTLOOK_FW_PLAIN, "TR: Field trip"),
    (OUTLOOK_FW_PLAIN, "RV: Field trip"),
    (OUTLOOK_FW_PLAIN_DE, "WG: Ausflug"),
], ids=["fw", "fwd", "fw-spaced", "tr", "rv", "wg-german"])
def test_strip_quotes_keeps_an_outlook_forward(text, subject):
    assert strip_quotes(text, subject=subject) == text.strip()


def test_strip_quotes_still_cuts_an_outlook_reply():
    assert strip_quotes(OUTLOOK_FW_PLAIN, subject="RE: Field trip") == "Can you handle this one?"
    # Only a forward prefix at the very start makes it a forward.
    assert strip_quotes(OUTLOOK_FW_PLAIN, subject="Re: Fwd: Field trip") == "Can you handle this one?"
    assert strip_quotes(OUTLOOK_FW_PLAIN_DE) == "Kannst du das übernehmen?"


def test_strip_quotes_does_not_cut_away_everything():
    # A note-to-self forward with nothing written above the forwarded block.
    note = OUTLOOK_FW_PLAIN.split("\n\n", 1)[1]
    assert strip_quotes(note) == note.strip()
    original = "-----Original Message-----\nFrom: A\nSent: x\n\nSign the slip.\n"
    assert strip_quotes(original) == original.strip()
    memo = (
        "From: Head teacher\n"
        "Date: 5 October 2026\n"
        "To: Parents of class 3b\n"
        "Subject: Parent evening\n\n"
        "Please book a slot for the parent evening by Friday.\n"
    )
    assert strip_quotes(memo) == memo.strip()


# An attachment-only Outlook reply: nothing of its own above the quoted request.
EMPTY_REPLY_PLAIN = (
    "\n\n"
    "From: Me <me@proton.me>\n"
    "Sent: Monday, October 5, 2026 9:00 AM\n"
    "To: Teacher <t@school.example>\n"
    "Subject: Form\n\n"
    "Could you please send me the permission form by Friday?\n"
)
EMPTY_REPLY_HTML = (
    '<html><body><div><br></div><hr style="display:inline-block;width:98%">'
    '<div id="divRplyFwdMsg" dir="ltr"><b>From:</b> Me &lt;me@proton.me&gt;<br><b>Sent:</b> Monday<br>'
    "<b>To:</b> Teacher<br><b>Subject:</b> Form</div>"
    "<div>Could you please send me the permission form by Friday?</div></body></html>"
)


@pytest.mark.parametrize("subject", ["RE: Form", "Re: Fwd: Form", "AW: Form", "Re[2]: Form", "SV: Form",
                                     "Antw: Form"])
def test_a_reply_with_no_text_of_its_own_strips_to_nothing(subject):
    # The quoted original is the owner's own request: it must not reach the
    # model again just because the reply carried only an attachment.
    assert strip_quotes(EMPTY_REPLY_PLAIN, subject=subject) == ""
    assert strip_quotes(html_to_text(EMPTY_REPLY_HTML, reply=True), subject=subject) == ""


def test_an_html_reply_with_no_text_of_its_own_renders_to_nothing():
    assert html_to_text(EMPTY_REPLY_HTML, reply=True) == ""
    # Not a reply (a note to self, a memo): the quoted block is all there is.
    assert "permission form" in html_to_text(EMPTY_REPLY_HTML)
    raw = (
        "Message-ID: <r1@school.example>\nFrom: Teacher <t@school.example>\nSubject: RE: Form\n"
        "Content-Type: text/html; charset=utf-8\n\n" + EMPTY_REPLY_HTML + "\n"
    ).encode()
    m = parse_message(raw)
    assert m.html_used is True
    assert m.text == ""
    assert "permission form" in parse_message(raw.replace(b"RE: Form", b"Form")).text


def test_a_reply_subject_does_not_drop_a_bottom_posted_reply():
    text = ("On 10/5/26 9:00 AM, Ms Smith wrote:\n> Can you bring the nets on Thursday?\n\n"
            "Yes, I will bring the nets.\n")
    assert strip_quotes(text, subject="Re: Nets") == "Yes, I will bring the nets."
    assert strip_quotes(OUTLOOK_FW_PLAIN, subject="RE: Field trip") == "Can you handle this one?"


def test_strip_quotes_is_linear_in_underscore_lines():
    text = "Hello\n" + "\n".join(["_" * 30] * 50_000)
    started = time.perf_counter()
    strip_quotes(text)
    assert time.perf_counter() - started < 1.0


def test_outlook_html_forward_keeps_the_forwarded_request():
    m = parsed("fix_outlook_forward.eml")
    assert m.html_used is True
    assert m.text.startswith("Can you handle this one?")
    assert "Please sign the field trip permission slip" in m.text
    assert "Please sign the field trip permission slip" in strip_quotes(m.text, subject=m.subject)
    html = load("fix_outlook_forward.eml").decode().split("\n\n", 1)[1]
    assert "permission slip" in html_to_text(html, keep_forwarded=True)
    assert html_to_text(html) == "Can you handle this one?"


def test_outlook_html_note_to_self_forward_keeps_its_content():
    # No "FW:" prefix: the forwarded block is all there is, so removing it
    # would leave nothing.
    m = parsed("fix_outlook_note_to_self.eml")
    assert m.html_used is True
    assert "Please sign the field trip permission slip" in m.text
    assert "Please sign the field trip permission slip" in strip_quotes(m.text, subject=m.subject)


def test_no_message_id_uses_a_stable_hash_key():
    raw = load("msg_no_message_id.eml")
    a, b = parse_message(raw), parse_message(raw)
    assert a.message_id is None
    assert ledger_key(a).startswith("hash:")
    assert ledger_key(a) == ledger_key(b)
    changed = parse_message(raw.replace(b"by Friday", b"by Monday"))
    assert ledger_key(changed) != ledger_key(a)
    assert thread_id(a) == ledger_key(a)


def test_message_id_key_and_thread_root():
    m = parsed("msg_plain_request.eml")
    assert ledger_key(m) == "mid:req-001@school.example"
    assert thread_id(m) == "mid:root-001@school.example"


def test_bridge_internal_reference_is_ignored():
    m = parsed("msg_bridge_references.eml")
    assert m.references == ("root@school.example",)
    assert thread_id(m) == "mid:root@school.example"
    solo = parsed("msg_internal_reference_only.eml")
    assert solo.references == ()
    assert thread_id(solo) == ledger_key(solo) == "mid:new-003@school.example"


def test_internal_in_reply_to_is_ignored_case_insensitively():
    raw = (b"Message-ID: <x@school.example>\nIn-Reply-To: <ABC@ProtonMail.Internalid>\n"
           b"From: a@school.example\n\nhi\n")
    m = parse_message(raw)
    assert m.in_reply_to is None
    assert thread_id(m) == "mid:x@school.example"


def test_encoded_headers_decode():
    m = parsed("msg_encoded_headers.eml")
    assert m.from_name == "Müller, Frau"
    assert m.from_addr == "office@school.example"
    assert m.from_count == 1
    assert m.subject == "Elternabend – Einladung für Donnerstag"


def test_calendar_part_is_collected_and_not_text():
    m = parsed("msg_ics_invite.eml")
    assert len(m.calendars) == 1
    cal = m.calendars[0]
    assert cal.filename == "invite.ics"
    assert cal.content_type == "text/calendar"
    assert b"BEGIN:VCALENDAR" in cal.data
    assert "BEGIN:VCALENDAR" not in m.text and "VEVENT" not in m.text
    assert m.text.startswith("You are invited")


def test_calendar_parts_are_capped():
    parts = "".join(
        f"--B\nContent-Type: text/calendar\n\nBEGIN:VCALENDAR\nX:{i}\nEND:VCALENDAR\n"
        for i in range(message.MAX_CALENDAR_PARTS + 3)
    )
    raw = f"From: a@school.example\nContent-Type: multipart/mixed; boundary=B\n\n{parts}--B--\n"
    assert len(parse_message(raw.encode()).calendars) == message.MAX_CALENDAR_PARTS


def test_garbage_never_raises():
    m = parse_message(b"\x00\xff not an email")
    assert m.from_addr is None and m.from_count == 0 and m.message_id is None
    assert ledger_key(m).startswith("hash:")
    assert parse_message(b"").text == ""
    broken = parsed("msg_broken_headers.eml")
    assert broken.from_addr == "office@school.example"
    assert broken.date is None
    assert "still readable" in broken.subject
    # Non-UTF-8 header bytes must not leave lone surrogates behind.
    odd = parse_message(b"Subject: caf\xe9 \xff\nFrom: a@school.example\n\nbody\n")
    odd.subject.encode("utf-8")
    ledger_key(odd)


@pytest.mark.parametrize("header", ["From", "To", "Cc"])
def test_deeply_nested_address_comments_do_not_raise(header):
    raw = (f"{header}: me@proton.me " + "(" * 600 + ")" * 600 + "\nSubject: x\n\nbody\n").encode()
    m = parse_message(raw)
    assert m.subject == "x" and m.text.strip() == "body"
    assert m.from_addr is None and m.from_count == 0 and m.to == () and m.cc == ()


def test_raw_utf8_headers_decode():
    raw = (
        "Message-ID: <utf8-001@school.example>\r\n"
        "From: Jürgen Müller <office@school.example>\r\n"
        "To: \"Müller, Ich\" <me@proton.me>\r\n"
        "Subject: Rückmeldung\r\n\r\n"
        "Bitte bis Freitag.\r\n"
    ).encode("utf-8")
    m = parse_message(raw)
    assert m.subject == "Rückmeldung"
    assert header_value(m, "Subject") == "Rückmeldung"
    assert m.from_name == "Jürgen Müller"
    assert m.from_addr == "office@school.example" and m.from_count == 1
    assert m.to == ("me@proton.me",)


def test_two_from_addresses_are_counted():
    m = parsed("msg_two_from.eml")
    assert m.from_count == 2
    # A second, malformed address still counts.
    bad = parse_message(b"From: a@school.example, not-an-address\n\nx\n")
    assert bad.from_count == 2
    # So does a repeated header.
    rep = parse_message(b"From: a@school.example\nFrom: b@school.example\n\nx\n")
    assert rep.from_count == 2


def test_plain_is_preferred_unless_it_is_a_stub():
    long_plain = (
        b"Content-Type: multipart/alternative; boundary=B\n\n"
        b"--B\nContent-Type: text/plain\n\nThis plain part is certainly long enough.\n"
        b"--B\nContent-Type: text/html\n\n<p>The html part</p>\n--B--\n"
    )
    m = parse_message(long_plain)
    assert m.html_used is False and m.text.startswith("This plain part")
    stub = long_plain.replace(b"This plain part is certainly long enough.", b"View in browser")
    m = parse_message(stub)
    assert m.html_used is True and m.text == "The html part"


def test_attachment_text_is_not_body():
    raw = (
        b"Content-Type: multipart/mixed; boundary=B\n\n"
        b"--B\nContent-Type: text/plain\nContent-Disposition: attachment; filename=n.txt\n\n"
        b"attached notes that are not the body\n--B--\n"
    )
    assert parse_message(raw).text == ""


def test_date_without_zone_is_utc():
    m = parse_message(b"Date: Mon, 05 Oct 2026 09:30:00 -0000\nFrom: a@school.example\n\nx\n")
    assert m.date is not None and m.date.utcoffset() == timedelta(0)


def test_subject_is_collapsed_and_capped():
    m = parse_message(b"Subject: a   b\n\tc\nFrom: a@school.example\n\nx\n")
    assert m.subject == "a b c"
    long = parse_message(("Subject: " + "x" * 800 + "\nFrom: a@school.example\n\nx\n").encode())
    assert len(long.subject) == 500


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    ("<a@b.example>", "a@b.example"),
    ("  <a@b.example> trailing", "a@b.example"),
    ("a@b.example other", "a@b.example"),
    ("<a b@c.example>", None),
    ("<>", None),
    ("<" + "x" * 999 + ">", None),
])
def test_normalize_message_id(value, expected):
    assert normalize_message_id(value) == expected


def test_parse_id_list():
    assert parse_id_list("<a@x.example> <b@x.example>\n <a@x.example>") == ["a@x.example", "b@x.example"]
    assert parse_id_list("a@x.example junk b@x.example") == ["a@x.example", "b@x.example"]
    assert parse_id_list("<bad id@x.example>") == []
    assert parse_id_list(None) == []


def test_normalize_body():
    assert normalize_body("  Hello \n\tWORLD  ") == "hello world"
