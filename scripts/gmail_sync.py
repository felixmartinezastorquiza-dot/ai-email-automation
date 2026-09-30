"""Optional: triage unread Gmail messages and label them in Gmail.

Setup and caveats: docs/gmail-integration.md. Requires: pip install -e ".[gmail]"

Usage:
    python scripts/gmail_sync.py            # process up to 20 unread inbox messages
"""

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.auth.transport.requests import Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.gmail import (  # noqa: E402
    LABEL_PREFIX,
    SCOPES,
    ensure_label,
    fetch_unread,
    label_and_mark_read,
)
from app.llm import create_chat_model  # noqa: E402
from app.processing import process_claimed  # noqa: E402
from app.store import EmailStore  # noqa: E402

CREDENTIALS_FILE = ROOT / "credentials.json"  # OAuth client from Google Cloud (not committed)
TOKEN_FILE = ROOT / "token.json"  # created on first login (not committed)


def gmail_service():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(message)s")
    store = EmailStore(settings.database_url.get_secret_value())
    store.init_schema()
    chat_model = create_chat_model(settings)
    service = gmail_service()
    labels: dict[str, str] = {}

    for message_id, incoming in fetch_unread(service):
        stored = store.add(incoming, source="gmail")
        claimed = store.claim(stored.id)
        if claimed is None:
            continue
        result = process_claimed(store, claimed, chat_model)
        tag = result.category or "needs_review"
        label_id = ensure_label(service, f"{LABEL_PREFIX}/{tag}", labels)
        label_and_mark_read(service, message_id, label_id)
        print(f"{tag:<16} {result.urgency or '-':<7} {incoming.subject[:60]}")


if __name__ == "__main__":
    main()
