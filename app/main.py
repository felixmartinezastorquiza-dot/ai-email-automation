"""FastAPI entry point: HTMX dashboard plus a small JSON API."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, ValidationError

from app.classifier import TriageStatus, classify_email
from app.config import get_settings
from app.digest import DailyDigest, build_digest, count
from app.emails import EmailAnalysis, IncomingEmail
from app.eml import EmailParseError, parse_eml
from app.exports import emails_to_csv
from app.llm import ChatModel, LLMUnavailableError, create_chat_model
from app.processing import format_minutes, load_sample_emails, process_claimed
from app.rate_limit import DailyQuota, SlidingWindowRateLimiter, client_ip
from app.store import EmailFilter, EmailStore, StoredEmail

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
MAX_EML_BYTES = 1_000_000

# Latest daily digest, keyed by today's triaged emails so it's regenerated only on changes.
digest_cache: dict[tuple, DailyDigest] = {}

CATEGORY_LABELS = {
    "inquiry": "Inquiry",
    "viewing_request": "Viewing",
    "complaint": "Complaint",
    "spam": "Spam",
}
CATEGORY_PLURALS = {
    "inquiry": "inquiries",
    "viewing_request": "viewings",
    "complaint": "complaints",
    "spam": "spam",
}
FILTER_LABELS = {
    EmailFilter.ALL: "All",
    EmailFilter.HIGH: "High urgency",
    EmailFilter.VIEWING: "Viewings",
    EmailFilter.COMPLAINT: "Complaints",
    EmailFilter.INQUIRY: "Inquiries",
    EmailFilter.SPAM: "Spam",
    EmailFilter.REVIEW: "Needs review",
}


def format_day(value: date | None) -> str:
    return value.strftime("%a, %b %d").replace(" 0", " ") if value else "—"


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["day"] = format_day
templates.env.globals.update(
    settings=settings,
    category_labels=CATEGORY_LABELS,
    category_plurals=CATEGORY_PLURALS,
    filter_labels=FILTER_LABELS,
)


@lru_cache
def get_store() -> EmailStore:
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not set")
    return EmailStore(settings.database_url.get_secret_value())


@lru_cache
def get_chat_model() -> ChatModel:
    return create_chat_model(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        store = get_store()
        await run_in_threadpool(store.init_schema)
        if await run_in_threadpool(store.is_empty):
            await run_in_threadpool(store.reset, load_sample_emails())
            logger.info("Loaded the sample inbox")
    except Exception:  # the app should still start and report errors per request
        logger.exception("Could not prepare the database on startup")
    yield


app = FastAPI(
    title=settings.app_name,
    description="AI triage for a real estate inbox: category, urgency and lead data.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

process_limiter = SlidingWindowRateLimiter(settings.rate_limit_process_per_minute, 60)
form_limiter = SlidingWindowRateLimiter(settings.rate_limit_form_per_hour, 3600)
llm_quota = DailyQuota(settings.max_daily_llm_runs)


def reset_rate_limits() -> None:
    for guard in (process_limiter, form_limiter, llm_quota):
        guard.reset()
    digest_cache.clear()


def limit_message(request: Request, limiter: SlidingWindowRateLimiter) -> str | None:
    """None if the request may use the AI, otherwise a friendly explanation."""
    retry_after = limiter.check(client_ip(request, settings.trusted_proxy_hops))
    if retry_after is not None:
        return f"Too many requests in a short time. Please wait {int(retry_after) + 1} seconds."
    if not llm_quota.consume():
        return "This demo has reached its daily AI usage limit. Please come back tomorrow."
    return None


StoreDep = Annotated[EmailStore, Depends(get_store)]
ModelDep = Annotated[ChatModel, Depends(get_chat_model)]


def inbox_context(
    store: EmailStore,
    email_filter: EmailFilter,
    *,
    selected: StoredEmail | None = None,
    processing: bool = False,
    notice: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    stats = store.stats()
    return {
        "stats": stats,
        "time_saved": format_minutes(stats.processed * settings.manual_minutes_per_email),
        "emails": store.list_emails(email_filter),
        "filter": email_filter,
        "selected": selected,
        "processing": processing and stats.new > 0,
        "notice": notice,
        "error": error,
    }


def render(request: Request, template: str, context: dict[str, Any], **headers: str):
    return templates.TemplateResponse(request, template, context, headers=headers or None)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, store: StoreDep) -> HTMLResponse:
    context = inbox_context(store, EmailFilter.ALL)
    context["form"] = {}
    return render(request, "index.html", context)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and the hosting platform."""
    return {"status": "ok"}


@app.get("/inbox", response_class=HTMLResponse, include_in_schema=False)
def inbox(request: Request, store: StoreDep, filter: EmailFilter = EmailFilter.ALL):
    return render(request, "_inbox.html", inbox_context(store, filter))


@app.post("/inbox/process-next", response_class=HTMLResponse, include_in_schema=False)
def process_next(
    request: Request,
    store: StoreDep,
    chat_model: ModelDep,
    filter: Annotated[EmailFilter, Form()] = EmailFilter.ALL,
):
    """Process one email; the returned panel asks for the next one until the inbox is empty."""
    if message := limit_message(request, process_limiter):
        return render(request, "_inbox.html", inbox_context(store, filter, error=message))

    done = "Inbox processed. Every email is classified and ready for the team."
    email = store.claim_next()
    if email is None:
        return render(request, "_inbox.html", inbox_context(store, filter, notice=done))
    try:
        processed = process_claimed(store, email, chat_model)
    except LLMUnavailableError as exc:
        return render(request, "_inbox.html", inbox_context(store, filter, error=str(exc)))

    context = inbox_context(store, filter, selected=processed, processing=True)
    context["detail_oob"] = True
    if not context["processing"]:  # that was the last email
        context["notice"] = done
    return render(request, "_inbox.html", context)


@app.get("/emails/{email_id}", response_class=HTMLResponse, include_in_schema=False)
def email_detail(request: Request, email_id: int, store: StoreDep):
    email = store.get(email_id)
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return render(request, "_detail.html", {"selected": email})


def compose_error(request: Request, message: str, form: dict[str, str]):
    """Re-render only the compose card, in place (HTMX response headers)."""
    return render(
        request,
        "_compose.html",
        {"form": form, "form_error": message},
        **{"HX-Retarget": "#compose", "HX-Reswap": "outerHTML"},
    )


def triage_new_email(
    request: Request,
    store: EmailStore,
    chat_model: ChatModel,
    incoming: IncomingEmail,
    source: str,
    form: dict[str, str],
):
    """Add an email to the inbox, triage it right away and show the result."""
    if message := limit_message(request, form_limiter):
        return compose_error(request, message, form)

    stored = store.add(incoming, source=source)
    claimed = store.claim(stored.id)
    try:
        processed = process_claimed(store, claimed, chat_model) if claimed else stored
    except LLMUnavailableError as exc:
        return compose_error(request, str(exc), form)

    context = inbox_context(store, EmailFilter.ALL, selected=processed)
    context.update(detail_oob=True, compose_oob=True, form={})
    return render(request, "_inbox.html", context)


@app.post("/emails", response_class=HTMLResponse, include_in_schema=False)
def submit_email(
    request: Request,
    store: StoreDep,
    chat_model: ModelDep,
    from_name: Annotated[str, Form()] = "",
    from_email: Annotated[str, Form()] = "",
    subject: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
):
    """Web form: add a new email to the inbox and triage it right away."""
    form = {"from_name": from_name, "from_email": from_email, "subject": subject, "body": body}
    try:
        incoming = IncomingEmail(
            **{k: v.strip() for k, v in form.items()}, received_at=datetime.now(UTC)
        )
    except ValidationError:
        return compose_error(
            request, "Please fill in every field (message up to 5,000 characters).", form
        )
    return triage_new_email(request, store, chat_model, incoming, "form", form)


@app.post("/emails/eml", response_class=HTMLResponse, include_in_schema=False)
async def upload_eml(
    request: Request,
    store: StoreDep,
    chat_model: ModelDep,
    file: UploadFile,
):
    """Upload a .eml file (exported from Gmail or Outlook) and triage it."""
    data = await file.read(MAX_EML_BYTES + 1)
    if len(data) > MAX_EML_BYTES:
        return compose_error(request, "The .eml file is too large (max 1 MB).", {})
    try:
        incoming = parse_eml(data)
    except EmailParseError as exc:
        return compose_error(request, str(exc), {})
    return await run_in_threadpool(
        triage_new_email, request, store, chat_model, incoming, "eml", {}
    )


@app.get("/export.csv", include_in_schema=False)
def export_csv(store: StoreDep, filter: EmailFilter = EmailFilter.ALL) -> Response:
    """Download the triaged emails, ready for Excel or Google Sheets."""
    filename = f"oakridge-leads-{date.today().isoformat()}.csv"
    return Response(
        content=emails_to_csv(store.list_emails(filter)),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/summary", response_class=HTMLResponse, include_in_schema=False)
def daily_summary(request: Request, store: StoreDep, chat_model: ModelDep):
    """AI-written end-of-day summary of the triaged inbox."""
    emails = store.triaged()
    context: dict[str, Any] = {"digest": None, "counts": count(emails), "error": None}
    if not emails:
        context["error"] = "Nothing triaged yet. Process the inbox first."
        return render(request, "_digest.html", context)

    key = tuple((e.id, e.processed_at) for e in emails)
    digest = digest_cache.get(key)
    if digest is None:  # only call the LLM when the day's data actually changed
        if message := limit_message(request, process_limiter):
            context["error"] = message
            return render(request, "_digest.html", context)
        try:
            digest = build_digest(emails, chat_model)
        except LLMUnavailableError as exc:
            context["error"] = str(exc)
            return render(request, "_digest.html", context)
        if digest is not None:
            digest_cache.clear()
            digest_cache[key] = digest
    context["digest"] = digest
    context["error"] = None if digest else "The summary could not be generated. Try again."
    return render(request, "_digest.html", context)


@app.post("/reset", response_class=HTMLResponse, include_in_schema=False)
def reset_demo(request: Request, store: StoreDep):
    """Restore the 20 sample emails, unprocessed, and remove form submissions."""
    store.reset(load_sample_emails())
    context = inbox_context(store, EmailFilter.ALL, notice="Demo reset: 20 new sample emails.")
    context["detail_oob"] = True
    return render(request, "_inbox.html", context)


class TriageRequest(BaseModel):
    from_name: str = Field(min_length=1, max_length=120, examples=["Marcus Reed"])
    from_email: str = Field(min_length=3, max_length=200, examples=["mreed@example.com"])
    subject: str = Field(max_length=300, examples=["Can I see 88 Oak Hollow Drive tomorrow?"])
    body: str = Field(
        min_length=1,
        max_length=5000,
        examples=["Could I tour 88 Oak Hollow Drive tomorrow at 5 pm? Call 555-014-7780."],
    )
    received_at: datetime | None = None


class TriageResponse(BaseModel):
    status: TriageStatus
    analysis: EmailAnalysis | None
    attempts: int
    problems: list[str]


@app.post("/api/triage")
def api_triage(payload: TriageRequest, request: Request, chat_model: ModelDep) -> TriageResponse:
    """Triage one email without storing it. Useful for Zapier, Make or n8n integrations."""
    if message := limit_message(request, form_limiter):
        raise HTTPException(status_code=429, detail=message)
    incoming = IncomingEmail(
        **payload.model_dump(exclude={"received_at"}),
        received_at=payload.received_at or datetime.now(UTC),
    )
    try:
        result = classify_email(incoming, chat_model)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TriageResponse(
        status=result.status,
        analysis=result.analysis,
        attempts=result.attempts,
        problems=result.problems,
    )
