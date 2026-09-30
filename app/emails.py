"""Data shapes: an incoming email and the structured analysis the AI must return."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    INQUIRY = "inquiry"
    VIEWING_REQUEST = "viewing_request"
    COMPLAINT = "complaint"
    SPAM = "spam"


class Urgency(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IncomingEmail(BaseModel):
    from_name: str = Field(min_length=1, max_length=120)
    from_email: str = Field(min_length=3, max_length=200)
    subject: str = Field(max_length=300)
    body: str = Field(min_length=1, max_length=5000)
    received_at: datetime


class EmailAnalysis(BaseModel):
    """What the model must extract from every email."""

    category: Category
    urgency: Urgency
    contact_name: str | None = Field(
        description="Name of the person who wrote the email, or null for spam."
    )
    phone: str | None = Field(description="Phone number exactly as written, or null.")
    property: str | None = Field(
        description="Street address of the property mentioned (or its listing ID), or null."
    )
    requested_date: date | None = Field(
        description="Date the sender wants a viewing or visit, as YYYY-MM-DD, or null."
    )
    summary: str = Field(description="One short sentence in English: what the sender wants.")
