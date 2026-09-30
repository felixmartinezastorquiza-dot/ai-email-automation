from datetime import date

from app.classifier import TriageResult, TriageStatus
from app.emails import Category, EmailAnalysis, Urgency
from app.store import EmailFilter, EmailStore


def result(category=Category.INQUIRY, urgency=Urgency.LOW) -> TriageResult:
    analysis = EmailAnalysis(
        category=category,
        urgency=urgency,
        contact_name="Test Person",
        phone=None,
        property=None,
        requested_date=date(2026, 10, 3) if category == Category.VIEWING_REQUEST else None,
        summary="Test summary.",
    )
    return TriageResult(TriageStatus.PROCESSED, analysis, attempts=1)


def test_reset_loads_the_sample_inbox_unprocessed(store: EmailStore) -> None:
    stats = store.stats()

    assert stats.new == 20
    assert stats.processed == 0
    assert store.list_emails() == []  # nothing triaged yet


def test_claim_next_never_returns_the_same_email_twice(store: EmailStore) -> None:
    first = store.claim_next()
    second = store.claim_next()

    assert first is not None and second is not None
    assert first.id != second.id
    assert first.received_at <= second.received_at
    assert store.get(first.id).status == "processing"


def test_saved_results_are_listed_urgent_first(store: EmailStore) -> None:
    low = store.claim_next()
    high = store.claim_next()
    store.save_result(low.id, result(urgency=Urgency.LOW))
    store.save_result(high.id, result(Category.COMPLAINT, Urgency.HIGH))

    listed = store.list_emails()

    assert [e.id for e in listed] == [high.id, low.id]
    assert store.stats().high_urgency == 1


def test_needs_review_items_come_first_and_have_their_own_filter(store: EmailStore) -> None:
    high = store.claim_next()
    flagged = store.claim_next()
    store.save_result(high.id, result(Category.COMPLAINT, Urgency.HIGH))
    store.save_result(flagged.id, TriageResult(TriageStatus.NEEDS_REVIEW, None, 2, ["bad phone"]))

    assert store.list_emails()[0].id == flagged.id
    assert [e.id for e in store.list_emails(EmailFilter.REVIEW)] == [flagged.id]
    assert store.get(flagged.id).problems == ["bad phone"]


def test_released_email_goes_back_to_the_queue(store: EmailStore) -> None:
    email = store.claim_next()
    store.release(email.id)

    assert store.get(email.id).status == "new"
    assert store.stats().new == 20


def test_category_filter(store: EmailStore) -> None:
    viewing = store.claim_next()
    inquiry = store.claim_next()
    store.save_result(viewing.id, result(Category.VIEWING_REQUEST, Urgency.MEDIUM))
    store.save_result(inquiry.id, result())

    assert [e.id for e in store.list_emails(EmailFilter.VIEWING)] == [viewing.id]
    assert store.get(viewing.id).requested_date == date(2026, 10, 3)
