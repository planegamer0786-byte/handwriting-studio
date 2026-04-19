"""
tasks.py — Celery task definitions for Handwriting Studio.

Usage
-----
1. Start Redis:   redis-server
2. Start worker:  celery -A tasks worker --loglevel=info
3. The FastAPI app auto-detects the worker and offloads exports to it.
"""
from __future__ import annotations

import base64
import io
import os
import time

from celery import Celery

# ── Celery app ────────────────────────────────────────────────────────────────
broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
backend_url = os.getenv("CELERY_BACKEND_URL", "redis://localhost:6379/1")

celery_app = Celery(
    "handwriting_studio",
    broker=broker_url,
    backend=backend_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,          # results kept for 1 hour
    task_track_started=True,
)

# ── Import models here to avoid circular imports at module level ─────────────
from models import StyleSettings  # noqa: E402
from document_parser import parse_plain_text  # noqa: E402
from renderer import render  # noqa: E402


@celery_app.task(bind=True, max_retries=2)
def export_task(self, text: str, settings_dict: dict, output_format: str = "pdf") -> dict:
    """
    Async high-res render job.

    Returns
    -------
    dict with keys: status, images_b64 (list), pages, width, height, format
    """
    self.update_state(state="RENDERING", meta={"progress": 10})

    settings = StyleSettings(**settings_dict)
    nodes = parse_plain_text(text)

    self.update_state(state="RENDERING", meta={"progress": 30})

    result = render(
        nodes,
        settings,
        low_res=False,
        seed=int(time.time()) % 10000,
    )

    self.update_state(state="RENDERING", meta={"progress": 80})

    # Build response payload
    return {
        "status": "done",
        "images_b64": result.images_b64,
        "pages": result.pages,
        "width": result.width,
        "height": result.height,
        "format": output_format,
    }
