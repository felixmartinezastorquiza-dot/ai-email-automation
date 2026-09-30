"""Evaluate email triage on the 20 labeled sample emails in data/sample_emails.json.

Pass criterion: at least 18/20 emails classified in the right category.
Urgency and extracted fields are measured and reported as well.

Usage:
    python eval.py
"""

import json
import re
import sys
import time
from pathlib import Path

from app.classifier import TriageResult, TriageStatus, classify_email
from app.config import get_settings
from app.emails import IncomingEmail
from app.llm import create_chat_model

SAMPLES_PATH = Path(__file__).resolve().parent / "data" / "sample_emails.json"
MIN_CORRECT_CATEGORIES = 18
FIELDS = ["name", "phone", "property", "requested_date"]


def digits(value: str | None) -> str | None:
    return re.sub(r"\D", "", value) if value else None


def field_matches(field: str, expected, result: TriageResult) -> bool:
    analysis = result.analysis
    if analysis is None:
        return False
    if field == "name":
        actual = analysis.contact_name
        return (actual or "").casefold() == (expected or "").casefold()
    if field == "phone":
        return digits(analysis.phone) == expected
    if field == "property":
        if expected is None:
            return analysis.property is None
        return expected.casefold() in (analysis.property or "").casefold()
    actual_date = analysis.requested_date.isoformat() if analysis.requested_date else None
    return actual_date == expected


def main() -> int:
    settings = get_settings()
    samples = json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))
    chat_model = create_chat_model(settings)

    print(f"Evaluating {len(samples)} emails with {settings.chat_model}...\n")
    started = time.perf_counter()
    category_ok = urgency_ok = needs_review = retried = 0
    field_ok = dict.fromkeys(FIELDS, 0)

    for sample in samples:
        expected = sample["expected"]
        email = IncomingEmail(**{k: sample[k] for k in IncomingEmail.model_fields})
        result = classify_email(email, chat_model)
        analysis = result.analysis

        cat_pass = analysis is not None and analysis.category == expected["category"]
        urg_pass = analysis is not None and analysis.urgency == expected["urgency"]
        category_ok += cat_pass
        urgency_ok += urg_pass
        needs_review += result.status == TriageStatus.NEEDS_REVIEW
        retried += result.attempts > 1
        wrong_fields = []
        for name in FIELDS:
            if field_matches(name, expected[name], result):
                field_ok[name] += 1
            else:
                wrong_fields.append(name)

        got = f"{analysis.category}/{analysis.urgency}" if analysis else "needs_review"
        mark = "PASS" if cat_pass else "FAIL"
        notes = []
        if not urg_pass and analysis:
            notes.append(f"urgency expected {expected['urgency']}")
        if wrong_fields:
            notes.append(f"fields off: {', '.join(wrong_fields)}")
        subject = sample["subject"][:44]
        print(f"  [{mark}] #{sample['id']:>2} {subject:<44} {got:<24} {'; '.join(notes)}")

    total = len(samples)
    ok = category_ok >= MIN_CORRECT_CATEGORIES
    print("\nSummary")
    print(f"  Category correct:    {category_ok}/{total} (target >= {MIN_CORRECT_CATEGORIES})")
    print(f"  Urgency correct:     {urgency_ok}/{total}")
    for name in FIELDS:
        print(f"  {name + ' correct:':<21}{field_ok[name]}/{total}")
    print(f"  Needed a retry:      {retried}   Flagged for review: {needs_review}")
    print(f"  Time: {time.perf_counter() - started:.1f}s")
    print(f"  Result: {'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
