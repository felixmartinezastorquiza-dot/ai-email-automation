"""FastAPI entry point."""

import logging

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and the hosting platform."""
    return {"status": "ok"}
