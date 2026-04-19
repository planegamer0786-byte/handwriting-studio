"""
main.py — FastAPI application for the Handwriting Studio.

Endpoints
---------
GET  /                     health check
POST /preview              low-res JPEG preview (sync, <400ms target)
POST /generate             alias for /preview (single-page convenience)
POST /export               start async high-res export job
GET  /export/{job_id}      poll export job status
POST /upload/document      parse DOCX/PDF → plain text
POST /upload/image         accept image for inline insertion
"""
from __future__ import annotations

import base64
import io
import os
import time
import uuid
from typing import Annotated

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel

from document_parser import parse_document, nodes_to_plain_text
from models import (
    PreviewRequest, PreviewResponse,
    ExportRequest, ExportStatusResponse,
    StyleSettings,
)
from renderer import render
from document_parser import parse_plain_text

# ── Celery (optional — falls back to threading if Redis unavailable) ──────────
# We do a real broker ping so _CELERY_AVAILABLE reflects actual connectivity,
# not just whether the 'celery' package is installed.
_CELERY_AVAILABLE = False
try:
    from tasks import celery_app, export_task
    celery_app.control.ping(timeout=1.0)   # raises if broker is unreachable
    _CELERY_AVAILABLE = True
except Exception:
    pass   # Redis not running → thread fallback

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Handwriting Studio API",
    description="Converts text/DOCX/PDF into realistic handwritten A4 page images.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-process job store (use Redis + Celery in production) ──────────────────
_JOBS: dict[str, dict] = {}


def _ensure_rgb_png(b64_str: str) -> bytes:
    """img2pdf chokes on RGBA PNGs — convert to RGB before passing."""
    raw = base64.b64decode(b64_str)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/", tags=["meta"])
def health():
    return {"status": "ok", "version": "2.0.0", "service": "handwriting-studio"}


# ── Preview (synchronous, low-res) ───────────────────────────────────────────
@app.post("/preview", response_model=PreviewResponse, tags=["render"])
def preview(req: PreviewRequest):
    """
    Renders a low-resolution (50%) JPEG preview.
    Target latency: < 400ms. Uses simplified noise pipeline.
    """
    nodes = parse_plain_text(req.text)
    result = render(nodes, req.settings, low_res=True, seed=42)

    return PreviewResponse(
        image=result.images_b64[0],   # first page only for preview
        pages=result.pages,
        width=result.width,
        height=result.height,
        render_ms=result.render_ms,
    )


# ── /generate alias (matches frontend convention) ────────────────────────────
class GenerateRequest(BaseModel):
    text: str
    settings: StyleSettings = StyleSettings()

class GenerateResponse(BaseModel):
    image: str
    images: list[str]
    pages: int
    width: int
    height: int
    render_ms: int

@app.post("/generate", response_model=GenerateResponse, tags=["render"])
def generate(req: GenerateRequest):
    """
    Synchronous full-resolution render (all pages).
    Suitable for short documents; use /export for large ones.
    """
    nodes = parse_plain_text(req.text)
    result = render(nodes, req.settings, low_res=False, seed=42)
    return GenerateResponse(
        image=result.images_b64[0],
        images=result.images_b64,
        pages=result.pages,
        width=result.width,
        height=result.height,
        render_ms=result.render_ms,
    )


# ── Async export ──────────────────────────────────────────────────────────────
@app.post("/export", tags=["export"])
def start_export(req: ExportRequest):
    """Enqueue a high-resolution export job. Returns a job_id to poll."""
    job_id = str(uuid.uuid4())

    # ── Production path: Celery + Redis ──────────────────────────────────────
    if _CELERY_AVAILABLE:
        task = export_task.delay(
            text=req.text,
            settings_dict=req.settings.model_dump(),
            output_format=req.output_format,
        )
        # Mirror Celery task state into our in-process _JOBS dict
        # so the polling endpoint stays uniform
        _JOBS[job_id] = {
            "status": "queued",
            "progress": 0,
            "celery_task_id": task.id,
        }
        return {"job_id": job_id}

    # ── Fallback: in-process threading (dev / single-node) ───────────────────
    _JOBS[job_id] = {"status": "queued", "progress": 0}
    import threading

    def _run():
        try:
            _JOBS[job_id]["status"] = "rendering"
            nodes = parse_plain_text(req.text)
            result = render(
                nodes, req.settings,
                low_res=False,
                seed=int(time.time()) % 10000,
            )
            _JOBS[job_id].update({
                "status": "done",
                "progress": 100,
                "images_b64": result.images_b64,
                "pages": result.pages,
                "width": result.width,
                "height": result.height,
                "format": req.output_format,
            })
        except Exception as e:
            _JOBS[job_id].update({"status": "failed", "error": str(e)})

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/export/{job_id}", response_model=ExportStatusResponse, tags=["export"])
def export_status(job_id: str):
    """Poll an export job. When status=done, download_url contains the data URI."""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    # ── If backed by Celery, sync state from the worker ──────────────────────
    celery_task_id = job.get("celery_task_id")
    if celery_task_id and _CELERY_AVAILABLE:
        from celery.result import AsyncResult
        from tasks import celery_app
        async_res = AsyncResult(celery_task_id, app=celery_app)
        if async_res.state == "PENDING":
            job["status"] = "queued"
        elif async_res.state in ("RENDERING", "STARTED"):
            job["status"] = "rendering"
            job["progress"] = async_res.info.get("progress", 50) if async_res.info else 50
        elif async_res.state == "SUCCESS":
            result = async_res.get()
            job.update(result)
        elif async_res.state in ("FAILURE", "REVOKED"):
            job.update({"status": "failed", "error": str(async_res.result)})

    if job["status"] != "done":
        return ExportStatusResponse(
            job_id=job_id,
            status=job["status"],
            progress=job.get("progress", 0),
            error=job.get("error", ""),
        )

    # Build a multi-page PDF or return first PNG
    fmt = job.get("format", "pdf")
    images_b64 = job["images_b64"]

    if fmt == "pdf":
        try:
            import img2pdf
            img_bytes_list = [_ensure_rgb_png(b) for b in images_b64]
            pdf_bytes = img2pdf.convert(img_bytes_list)
            data_uri = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode()
        except Exception:
            # Fallback: return first page PNG if img2pdf fails
            data_uri = "data:image/png;base64," + images_b64[0]
    else:
        data_uri = "data:image/png;base64," + images_b64[0]

    return ExportStatusResponse(
        job_id=job_id,
        status="done",
        progress=100,
        download_url=data_uri,
    )


# ── Document upload ───────────────────────────────────────────────────────────
@app.post("/upload/document", tags=["upload"])
async def upload_document(file: UploadFile = File(...)):
    """
    Accept a DOCX or PDF file.
    Returns the extracted plain text for the editor, plus a page count.
    """
    content = await file.read()
    mime = file.content_type or ""

    try:
        nodes = parse_document(content, mime)
        text  = nodes_to_plain_text(nodes)
        return {
            "text": text,
            "node_count": len(nodes),
            "filename": file.filename,
        }
    except Exception as e:
        raise HTTPException(400, f"Could not parse document: {e}")


# ── Image upload (for inline diagram insertion) ───────────────────────────────
@app.post("/upload/image", tags=["upload"])
async def upload_image(file: UploadFile = File(...)):
    """
    Accept a PNG/JPG diagram. Returns base64 so the frontend can
    embed it in the text as a placeholder, and the backend can
    decode it during render.
    """
    content = await file.read()
    try:
        img = __import__("PIL.Image", fromlist=["Image"]).open(io.BytesIO(content))
        img.verify()
    except Exception:
        raise HTTPException(400, "Invalid image file")

    b64 = base64.b64encode(content).decode()
    return {
        "image_b64": b64,
        "filename": file.filename,
        "size": len(content),
    }
