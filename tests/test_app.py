from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.llm import LLMUnavailableError
from app.main import app, get_chat_model
from app.processing import format_minutes, load_sample_emails
from app.rate_limit import SlidingWindowRateLimiter
from app.store import EmailStore

pytestmark = pytest.mark.usefixtures("client_app")

client = TestClient(app)

FORM = {
    "from_name": "Alex Morgan",
    "from_email": "alex@example.com",
    "subject": "Viewing this Friday?",
    "body": "Could I see 60 Aspen Way this Friday at 3 pm?",
}


def test_dashboard_shows_demo_notice_and_waiting_emails() -> None:
    page = client.get("/")

    assert page.status_code == 200
    assert "Demo project with sample data" in page.text
    assert "Built by" in page.text
    assert "waiting to be sorted" in page.text


def test_processing_one_email_asks_htmx_for_the_next(store: EmailStore) -> None:
    response = client.post("/inbox/process-next", data={"filter": "all"})

    assert response.status_code == 200
    assert 'hx-trigger="load delay:200ms"' in response.text  # keeps going
    assert 'hx-swap-oob="true"' in response.text  # updates the detail card too
    assert store.stats().new == 19


def test_processing_stops_when_the_inbox_is_empty(store: EmailStore) -> None:
    store.reset(load_sample_emails()[:2])  # a short inbox keeps the test fast
    client.post("/inbox/process-next", data={"filter": "all"})

    response = client.post("/inbox/process-next", data={"filter": "all"})  # the last one

    assert "Inbox processed" in response.text
    assert "hx-trigger" not in response.text
    assert store.stats().processed == 2


def test_ai_outage_shows_a_message_and_keeps_the_email_queued(store: EmailStore) -> None:
    class DownModel:
        def parse(self, *args):
            raise LLMUnavailableError("The AI service is temporarily unavailable.")

    app.dependency_overrides[get_chat_model] = DownModel

    response = client.post("/inbox/process-next", data={"filter": "all"})

    assert response.status_code == 200
    assert "temporarily unavailable" in response.text
    assert store.stats().new == 20


def test_form_email_is_triaged_and_shown(store: EmailStore) -> None:
    response = client.post("/emails", data=FORM)

    assert response.status_code == 200
    assert "Viewing this Friday?" in response.text
    assert store.stats().processed == 1


def test_incomplete_form_is_re_rendered_in_place() -> None:
    response = client.post("/emails", data=FORM | {"body": "  "})

    assert response.headers["HX-Retarget"] == "#compose"
    assert "Please fill in every field" in response.text


def test_form_is_rate_limited_per_visitor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "form_limiter", SlidingWindowRateLimiter(2, window_seconds=3600))
    for _ in range(2):
        client.post("/emails", data=FORM)

    response = client.post("/emails", data=FORM)

    assert "Too many requests" in response.text


def test_reset_restores_the_sample_inbox(store: EmailStore) -> None:
    client.post("/emails", data=FORM)
    client.post("/inbox/process-next", data={"filter": "all"})

    client.post("/reset")

    assert store.stats().new == 20
    assert store.stats().processed == 0


def test_filters_and_detail_view(store: EmailStore) -> None:
    client.post("/inbox/process-next", data={"filter": "all"})
    email_id = store.list_emails()[0].id

    assert client.get("/inbox?filter=needs_review").status_code == 200
    detail = client.get(f"/emails/{email_id}")
    assert "How the AI handled this email" in detail.text
    assert client.get("/emails/999999").status_code == 404


def test_json_api_triages_without_storing(store: EmailStore) -> None:
    response = client.post("/api/triage", json=FORM)

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert response.json()["analysis"]["category"] == "inquiry"
    assert store.stats().processed == 0


def test_eml_upload_is_triaged(store: EmailStore) -> None:
    eml = (Path(__file__).resolve().parent.parent / "data" / "sample.eml").read_bytes()

    response = client.post("/emails/eml", files={"file": ("garage.eml", eml, "message/rfc822")})

    assert response.status_code == 200
    assert "Garage door stuck" in response.text
    assert store.stats().processed == 1


def test_invalid_eml_shows_an_error_in_the_form() -> None:
    response = client.post("/emails/eml", files={"file": ("x.eml", b"not an email", "text/plain")})

    assert response.headers["HX-Retarget"] == "#compose"


def test_csv_export_downloads_triaged_emails() -> None:
    client.post("/inbox/process-next", data={"filter": "all"})

    response = client.get("/export.csv")

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert len(response.text.strip().splitlines()) == 2  # header + 1 email


def test_daily_summary_is_generated_once_and_cached(fake_model) -> None:
    client.post("/inbox/process-next", data={"filter": "all"})
    calls_before = fake_model.calls

    first = client.post("/summary")
    second = client.post("/summary")

    assert "Quiet day." in first.text and "Quiet day." in second.text
    assert fake_model.calls == calls_before + 1  # second request served from cache


def test_daily_summary_needs_processed_emails() -> None:
    response = client.post("/summary")

    assert "Process the inbox first" in response.text


def test_time_saved_formatting() -> None:
    assert format_minutes(0) == "0 min"
    assert format_minutes(45) == "45 min"
    assert format_minutes(60) == "1 h"
    assert format_minutes(75) == "1 h 15 min"
