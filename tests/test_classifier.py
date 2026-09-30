from datetime import date, datetime, timedelta, timezone

from app.classifier import TriageStatus, classify_email, find_problems, format_email
from app.emails import Category, EmailAnalysis, IncomingEmail, Urgency

RECEIVED = datetime(2026, 9, 28, 8, 40, tzinfo=timezone(timedelta(hours=-4)))

EMAIL = IncomingEmail(
    from_name="Marcus Reed",
    from_email="mreed@example.com",
    subject="Can I see 88 Oak Hollow Drive tomorrow?",
    body="Could I tour 88 Oak Hollow Drive tomorrow at 5 pm? Call 555-014-7780.",
    received_at=RECEIVED,
)


def analysis(**overrides) -> EmailAnalysis:
    values = {
        "category": Category.VIEWING_REQUEST,
        "urgency": Urgency.HIGH,
        "contact_name": "Marcus Reed",
        "phone": "555-014-7780",
        "property": "88 Oak Hollow Drive",
        "requested_date": date(2026, 9, 29),
        "summary": "Wants to tour 88 Oak Hollow Drive tomorrow at 5 pm.",
    }
    return EmailAnalysis(**(values | overrides))


class ScriptedModel:
    """Returns the given outputs in order and records every conversation it received."""

    def __init__(self, *outputs: EmailAnalysis | None) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[dict]] = []

    def parse(self, system, messages, output_format):
        self.calls.append(list(messages))
        return self.outputs.pop(0)


def test_valid_first_answer_is_processed_in_one_attempt() -> None:
    model = ScriptedModel(analysis())

    result = classify_email(EMAIL, model)

    assert result.status == TriageStatus.PROCESSED
    assert result.attempts == 1
    assert result.analysis == analysis()


def test_invalid_answer_is_retried_with_the_exact_problem() -> None:
    model = ScriptedModel(analysis(requested_date=date(2026, 9, 1)), analysis())

    result = classify_email(EMAIL, model)

    assert result.status == TriageStatus.PROCESSED
    assert result.attempts == 2
    feedback = model.calls[1][-1]["content"]
    assert "before the received date" in feedback


def test_two_invalid_answers_are_flagged_for_human_review() -> None:
    bad = analysis(phone="12")
    model = ScriptedModel(bad, bad)

    result = classify_email(EMAIL, model)

    assert result.status == TriageStatus.NEEDS_REVIEW
    assert result.analysis is None
    assert any("does not look like a phone number" in p for p in result.problems)


def test_missing_structured_output_counts_as_a_failed_attempt() -> None:
    model = ScriptedModel(None, None)

    result = classify_email(EMAIL, model)

    assert result.status == TriageStatus.NEEDS_REVIEW
    assert len(model.calls) == 2


def test_business_rules() -> None:
    assert find_problems(analysis(), EMAIL) == []
    assert find_problems(analysis(requested_date=date(2027, 12, 1)), EMAIL)
    assert find_problems(analysis(category=Category.INQUIRY), EMAIL)  # date only for viewings
    assert find_problems(
        analysis(category=Category.SPAM, urgency=Urgency.HIGH, requested_date=None), EMAIL
    )
    assert find_problems(analysis(summary="  "), EMAIL)


def test_email_is_wrapped_as_data_with_its_received_date() -> None:
    text = format_email(EMAIL)

    assert "Received: Monday 2026-09-28" in text
    assert "<email_body>" in text and "</email_body>" in text
