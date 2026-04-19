"""
models.py — shared data models for the handwriting rendering pipeline.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Pydantic API models ───────────────────────────────────────────────────────

class StyleSettings(BaseModel):
    """All user-controllable rendering parameters."""
    font_variant: Literal["Regular", "SemiBold", "Bold"] = "Regular"
    font_size: int              = Field(36, ge=14, le=72)
    ink_color: str              = Field("#1a1a2e", pattern=r"^#[0-9a-fA-F]{6}$")
    bg_color: str               = Field("#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    line_spacing: float         = Field(1.65, ge=1.0, le=3.0)
    margin_top: int             = Field(110, ge=20, le=350)
    margin_left: int            = Field(75,  ge=20, le=250)
    margin_right: int           = Field(50,  ge=10, le=200)
    margin_bottom: int          = Field(60,  ge=20, le=250)
    # Noise / realism
    noise_level: Literal["none", "low", "medium", "high"] = "medium"
    baseline_jitter: float      = Field(2.5, ge=0.0, le=8.0)
    pressure_variance: float    = Field(0.15, ge=0.0, le=0.4)
    rotation_jitter: float      = Field(1.2,  ge=0.0, le=5.0)
    word_spacing_variance: float= Field(0.15, ge=0.0, le=0.4)
    # Paper
    paper_template: Literal["plain", "ruled", "grid", "mjcet", "mjcet_assignment"] = "ruled"
    enable_scanner_effect: bool = True
    page_slant_deg: float       = Field(0.0, ge=-3.0, le=3.0)


class PreviewRequest(BaseModel):
    text: str           = Field(..., min_length=1, max_length=20_000)
    settings: StyleSettings = Field(default_factory=StyleSettings)


class PreviewResponse(BaseModel):
    image: str          # base64 JPEG
    pages: int
    width: int
    height: int
    render_ms: int


class ExportRequest(BaseModel):
    text: str           = Field(..., min_length=1, max_length=200_000)
    settings: StyleSettings = Field(default_factory=StyleSettings)
    output_format: Literal["png", "pdf"] = "pdf"
    resolution_scale: float = Field(1.0, ge=0.5, le=2.0)  # 2.0 = print quality


class ExportStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "rendering", "done", "failed"]
    progress: int       = 0     # 0-100
    download_url: str   = ""
    error: str          = ""


# ── Internal renderer types ───────────────────────────────────────────────────

@dataclass
class DocumentNode:
    kind: Literal["heading1", "heading2", "paragraph", "list_item", "image", "blank"]
    content: str = ""
    image_bytes: Optional[bytes] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class GlyphContext:
    char_index: int             = 0
    char_index_in_word: int     = 0
    word_index: int             = 0
    writing_speed: float        = 0.7   # 0-1, affects blur
    word_pressure: float        = 1.0   # 0.75-1.0
    is_heading: bool            = False


@dataclass
class LayoutCursor:
    x: int = 0
    y: int = 0
    page: int = 0


@dataclass
class RenderResult:
    images_b64: list[str]       # list of base64 PNG strings, one per page
    pages: int
    width: int
    height: int
    render_ms: int
