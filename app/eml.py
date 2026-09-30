"""Parse RFC 822 emails (.eml files, or Gmail's `format=raw` messages) into IncomingEmail."""

import html
import re
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime

from pydantic import ValidationError

from app.emails import IncomingEmail

MAX_BODY_CHARS = 5000


class EmailParseError(ValueError):
    """The file isn't a readable email with a text body."""


def html_to_text(markup: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>|</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", html.unescape(text))
    return re.sub(r" *\n *", "\n", text).strip()


def parse_received(date_header: str | None, fallback: datetime) -> datetime:
    if not date_header:
        return fallback
    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_eml(data: bytes, now: datetime | None = None) -> IncomingEmail:
    message = BytesParser(policy=policy.default).parsebytes(data)
    name, address = parseaddr(str(message.get("From", "")))
    if "@" not in address:
        raise EmailParseError("This file doesn't look like an email (no sender address).")

    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        raise EmailParseError("No text found in this email.")
    content = part.get_content()
    body = html_to_text(content) if part.get_content_type() == "text/html" else content

    try:
        return IncomingEmail(
            from_name=name or address,
            from_email=address,
            subject=str(message.get("Subject", "") or "(no subject)")[:300],
            body=body.strip()[:MAX_BODY_CHARS],
            received_at=parse_received(message.get("Date"), now or datetime.now(UTC)),
        )
    except ValidationError as exc:
        raise EmailParseError("This file doesn't look like an email with a message.") from exc
