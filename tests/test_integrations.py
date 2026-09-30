import base64
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.digest import build_digest, count, describe
from app.eml import EmailParseError, html_to_text, parse_eml
from app.exports import emails_to_csv, safe_cell
from app.gmail import raw_message_to_email
from app.store import StoredEmail

SAMPLE_EML = (Path(__file__).resolve().parent.parent / "data" / "sample.eml").read_bytes()
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def stored(**overrides) -> StoredEmail:
    values = dict(
        id=1,
        from_name="Priya Nair",
        from_email="priya@example.com",
        subject="Leak",
        body="Water leak",
        received_at=NOW,
        source="sample",
        status="processed",
        category="complaint",
        urgency="high",
        contact_name="Priya Nair",
        phone="555 014 6120",
        property="27 Maple Court",
        requested_date=None,
        summary="Water leaking near an outlet.",
        attempts=1,
        problems=[],
        processed_at=NOW,
    )
    return StoredEmail(**(values | overrides))


def test_eml_file_is_parsed_with_sender_date_and_plain_text() -> None:
    email = parse_eml(SAMPLE_EML)

    assert email.from_name == "Laura Chen"
    assert email.from_email == "laura.chen@example.com"
    assert email.subject == "Garage door stuck at 27 Maple Court"
    assert email.received_at.date() == date(2026, 9, 29)
    assert "555-014-3902" in email.body
    assert "<p>" not in email.body  # plain text part preferred over HTML


def test_html_only_email_is_converted_to_text() -> None:
    raw = (
        b"From: a@example.com\r\nSubject: Hi\r\nContent-Type: text/html\r\n\r\n"
        b"<p>Hello&nbsp;there</p><script>alert(1)</script>"
    )

    email = parse_eml(raw, now=NOW)

    assert email.body == "Hello\xa0there"
    assert email.received_at == NOW  # no Date header


def test_file_without_a_message_is_rejected() -> None:
    with pytest.raises(EmailParseError):
        parse_eml(b"From: a@example.com\r\nSubject: empty\r\n\r\n   ", now=NOW)


def test_gmail_raw_format_uses_the_same_parser() -> None:
    raw = base64.urlsafe_b64encode(SAMPLE_EML).decode().rstrip("=")  # Gmail omits padding

    email = raw_message_to_email({"id": "abc", "raw": raw})

    assert email.from_name == "Laura Chen"


def test_html_to_text_keeps_line_breaks() -> None:
    assert html_to_text("<p>One</p><p>Two<br>Three</p>") == "One\nTwo\nThree"


def test_csv_neutralizes_spreadsheet_formulas() -> None:
    assert safe_cell('=HYPERLINK("http://evil.example","click")').startswith("'=")
    assert safe_cell("+1 555 014 3345") == "'+1 555 014 3345"
    assert safe_cell("Normal text") == "Normal text"
    assert safe_cell(None) == ""


def test_csv_has_a_header_and_one_row_per_email() -> None:
    rows = emails_to_csv([stored(), stored(id=2, subject="=cmd")]).strip().splitlines()

    assert rows[0].startswith("received_at,status,category,urgency")
    assert len(rows) == 3
    assert "'=cmd" in rows[2]


class DigestModel:
    def __init__(self, digest) -> None:
        self.digest = digest
        self.prompt = ""

    def parse(self, system, messages, output_format):
        self.prompt = messages[0]["content"]
        return output_format(**self.digest)


def test_digest_lists_emails_and_caps_priorities() -> None:
    model = DigestModel({"headline": "Busy day.", "priorities": [f"Call {i}" for i in range(8)]})

    flagged = stored(id=2, status="needs_review", category=None, urgency=None)
    digest = build_digest([stored(), flagged], model)

    assert len(digest.priorities) == 5
    assert "2 emails triaged today, 1 high urgency, 1 need human review" in model.prompt
    assert "NEEDS HUMAN REVIEW" in model.prompt


def test_counts_are_computed_in_code_not_by_the_model() -> None:
    emails = [
        stored(),
        stored(id=2, category="viewing_request", urgency="high"),
        stored(id=3, category="spam", urgency="low"),
        stored(id=4, status="needs_review", category=None, urgency=None),
    ]

    counts = count(emails)

    assert (counts.total, counts.high, counts.needs_review) == (4, 2, 1)
    assert counts.by_category == {"viewing_request": 1, "complaint": 1, "spam": 1}


def test_describe_line_contains_the_key_facts() -> None:
    line = describe(stored(category="viewing_request", requested_date=date(2026, 10, 3)))

    assert "high urgency viewing_request" in line
    assert "27 Maple Court" in line
    assert "requested 2026-10-03" in line
