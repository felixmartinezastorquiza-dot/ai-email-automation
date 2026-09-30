"""Glue between storage and the classifier, plus the sample inbox."""

import json
from pathlib import Path

from app.classifier import classify_email
from app.emails import IncomingEmail
from app.llm import ChatModel, LLMUnavailableError
from app.store import EmailStore, StoredEmail

SAMPLES_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_emails.json"


def load_sample_emails(path: Path = SAMPLES_PATH) -> list[IncomingEmail]:
    samples = json.loads(path.read_text(encoding="utf-8"))
    return [IncomingEmail(**{k: s[k] for k in IncomingEmail.model_fields}) for s in samples]


def to_incoming(email: StoredEmail) -> IncomingEmail:
    return IncomingEmail(
        from_name=email.from_name,
        from_email=email.from_email,
        subject=email.subject,
        body=email.body,
        received_at=email.received_at,
    )


def process_claimed(store: EmailStore, email: StoredEmail, chat_model: ChatModel) -> StoredEmail:
    """Classify an email already claimed from the queue and save the result."""
    try:
        result = classify_email(to_incoming(email), chat_model)
    except LLMUnavailableError:
        store.release(email.id)  # back to the queue so it can be retried later
        raise
    return store.save_result(email.id, result)


def format_minutes(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    return f"{hours} h" if hours else f"{rest} min"
