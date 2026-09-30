"""Shared fixtures. Database tests run against TEST_DATABASE_URL and are skipped without it."""

from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.digest import DailyDigest
from app.emails import Category, EmailAnalysis, Urgency
from app.main import app, get_chat_model, get_store, reset_rate_limits
from app.processing import load_sample_emails
from app.store import EmailStore

_test_url = get_settings().test_database_url
TEST_DATABASE_URL = _test_url.get_secret_value() if _test_url else None


class FakeChatModel:
    """Deterministic stand-in for the LLM: every email becomes a low-urgency inquiry."""

    def __init__(self) -> None:
        self.calls = 0

    def parse(self, system, messages, output_format):
        self.calls += 1
        if output_format is DailyDigest:
            return DailyDigest(headline="Quiet day.", priorities=["Reply to inquiries"])
        return EmailAnalysis(
            category=Category.INQUIRY,
            urgency=Urgency.LOW,
            contact_name="Test Person",
            phone="555-014-0000",
            property="1 Test Street",
            requested_date=None,
            summary="Asks a question about a property.",
        )


@pytest.fixture(autouse=True)
def fresh_rate_limits() -> Iterator[None]:
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture(scope="session")
def shared_store() -> Iterator[EmailStore]:
    """One connection pool for the whole test run."""
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    test_store = EmailStore(TEST_DATABASE_URL)
    test_store.init_schema()
    yield test_store
    test_store.close()


@pytest.fixture
def store(shared_store: EmailStore) -> EmailStore:
    """Each test starts from the fresh sample inbox."""
    shared_store.reset(load_sample_emails())
    return shared_store


@pytest.fixture
def fake_model() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def client_app(store: EmailStore, fake_model: FakeChatModel) -> Iterator[None]:
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_chat_model] = lambda: fake_model
    yield
    app.dependency_overrides.clear()
