"""Optional Gmail integration helpers (see docs/gmail-integration.md).

The Gmail API returns messages with `format="raw"` as base64url-encoded RFC 822 text,
the same format as a .eml file, so they go through the same parser.
The Google client libraries are an optional extra: pip install -e ".[gmail]"
"""

import base64
from collections.abc import Iterator
from typing import Any

from app.emails import IncomingEmail
from app.eml import parse_eml

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # read, mark as read, add labels
LABEL_PREFIX = "Oakridge AI"


def raw_message_to_email(message: dict[str, Any]) -> IncomingEmail:
    raw = message["raw"]
    padded = raw + "=" * (-len(raw) % 4)
    return parse_eml(base64.urlsafe_b64decode(padded))


def fetch_unread(service: Any, max_results: int = 20) -> Iterator[tuple[str, IncomingEmail]]:
    """Yield (gmail_message_id, email) for unread messages in the inbox."""
    listing = (
        service.users()
        .messages()
        .list(userId="me", q="in:inbox is:unread", maxResults=max_results)
        .execute()
    )
    for ref in listing.get("messages", []):
        message = service.users().messages().get(userId="me", id=ref["id"], format="raw").execute()
        yield ref["id"], raw_message_to_email(message)


def ensure_label(service: Any, name: str, cache: dict[str, str]) -> str:
    """Return the ID of a Gmail label, creating it if needed."""
    if not cache:
        for label in service.users().labels().list(userId="me").execute().get("labels", []):
            cache[label["name"]] = label["id"]
    if name not in cache:
        created = service.users().labels().create(userId="me", body={"name": name}).execute()
        cache[name] = created["id"]
    return cache[name]


def label_and_mark_read(service: Any, message_id: str, label_id: str) -> None:
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id], "removeLabelIds": ["UNREAD"]},
    ).execute()
