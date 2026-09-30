"""CSV export of triaged emails, safe to open in Excel or Google Sheets."""

import csv
import io

from app.store import StoredEmail

COLUMNS = [
    "received_at",
    "status",
    "category",
    "urgency",
    "contact_name",
    "phone",
    "from_email",
    "property",
    "requested_date",
    "summary",
    "subject",
]

# Spreadsheet apps run cells starting with these characters as formulas.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    """Neutralize CSV injection: email content comes from strangers."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def emails_to_csv(emails: list[StoredEmail]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for email in emails:
        writer.writerow(safe_cell(getattr(email, column)) for column in COLUMNS)
    return buffer.getvalue()
