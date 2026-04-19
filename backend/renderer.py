"""
renderer.py — Core image rendering engine.

Architecture:
  1. Parse text into DocumentNode tree
  2. For each node, measure and word-wrap lines
  3. For each line, render glyphs one-by-one applying the noise pipeline
  4. When y-cursor overflows, start a new page canvas
  5. Optionally apply scanner-effect post-processing
  6. Return list of base64 PNG strings (one per page)
"""
from __future__ import annotations

import base64
import io
import math
import random
import time
from pathlib import Path
from typing import Generator

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

from models import DocumentNode, RenderResult, StyleSettings
from noise import HumanVariabilityEngine, make_noise_config
from document_parser import parse_plain_text

# ── Constants ─────────────────────────────────────────────────────────────────
CANVAS_W = 794
CANVAS_H = 1123
FONTS_DIR = Path(__file__).parent / "fonts"

# Paper template line/grid colors
RULE_COLOR   = (180, 200, 220, 255)   # faint blue ruled lines
GRID_COLOR   = (200, 210, 200, 180)   # faint green grid
MARGIN_COLOR = (220, 150, 150, 180)   # pink/red margin line

# MJCET template measurements (matches real MJCET answer sheets)
MJCET_MARGIN_X = 75
MJCET_HEADER_H = 105   # space for header block

# MJCET Assignment / Tutorial Sheet measurements
MJCET_ASSIGN_HEADER_H = 85   # compact single-bar header


# ── Font loading ──────────────────────────────────────────────────────────────

_FONT_CACHE: dict[tuple, ImageFont.FreeTypeFont] = {}

def _load_font(variant: str, size: int) -> ImageFont.FreeTypeFont:
    key = (variant, size)
    if key not in _FONT_CACHE:
        path = FONTS_DIR / f"Caveat-{variant}.ttf"
        if not path.exists():
            path = FONTS_DIR / "Caveat-Regular.ttf"
        _FONT_CACHE[key] = ImageFont.truetype(str(path), size)
    return _FONT_CACHE[key]


def _get_node_font(node: DocumentNode, settings: StyleSettings) -> tuple[ImageFont.FreeTypeFont, str]:
    """Return (font, ink_color) appropriate for this node type."""
    if node.kind == "heading1":
        return _load_font("Bold", settings.font_size + 8), settings.ink_color
    elif node.kind == "heading2":
        return _load_font("SemiBold", settings.font_size + 3), settings.ink_color
    elif node.kind == "list_item":
        return _load_font(settings.font_variant, settings.font_size), settings.ink_color
    else:
        return _load_font(settings.font_variant, settings.font_size), settings.ink_color


# ── Color utilities ───────────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ── Word-wrap ─────────────────────────────────────────────────────────────────

def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """Wrap text into lines that fit max_width. Preserves existing newlines."""
    lines: list[str] = []
    for paragraph in text.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        current: list[str] = []
        for word in words:
            candidate = " ".join(current + [word])
            bbox = draw.textbbox((0, 0), candidate, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
    return lines


# ── Paper templates ───────────────────────────────────────────────────────────

def _draw_ruled_lines(draw: ImageDraw.ImageDraw, line_h: int, margin_top: int) -> None:
    y = margin_top
    while y < CANVAS_H - 30:
        draw.line([(0, y), (CANVAS_W, y)], fill=RULE_COLOR[:3] + (60,), width=1)
        y += line_h


def _draw_grid(draw: ImageDraw.ImageDraw, line_h: int) -> None:
    # Horizontal
    y = 0
    while y < CANVAS_H:
        draw.line([(0, y), (CANVAS_W, y)], fill=GRID_COLOR[:3] + (55,), width=1)
        y += line_h
    # Vertical
    x = 0
    while x < CANVAS_W:
        draw.line([(x, 0), (x, CANVAS_H)], fill=GRID_COLOR[:3] + (55,), width=1)
        x += line_h


def _draw_mjcet_header(draw: ImageDraw.ImageDraw, scale: float = 1.0) -> None:
    """Draw MJCET header field labels and underline guides."""
    font_sm = _load_font("Regular", max(8, int(11 * scale)))
    # Layout: 2 columns × 2 rows  →  Name | Roll No  /  Subject | Date
    # (col, row): col selects left/right half; row selects top/bottom band
    fields = [
        ("Name:",     0, 0),
        ("Roll No:",  1, 0),
        ("Subject:",  0, 1),
        ("Date:",     1, 1),
    ]
    col_width = int(370 * scale)   # each column spans ~370px at full scale
    for label, col, row in fields:
        fx = int((20 + col * 380) * scale)
        fy = int((20 + row * 38) * scale)
        draw.text((fx, fy), label, font=font_sm, fill=(140, 140, 140))
        # Underline guide: from end-of-label to near column edge
        label_px = int(len(label) * 7 * scale)
        draw.line(
            [(fx + label_px + int(6 * scale), fy + int(17 * scale)),
             (fx + col_width - int(10 * scale), fy + int(17 * scale))],
            fill=(190, 190, 190), width=1,
        )


def _draw_mjcet_template(draw: ImageDraw.ImageDraw, line_h: int, scale: float = 1.0) -> None:
    hdr_h = int(MJCET_HEADER_H * scale)
    mgn_x = int(MJCET_MARGIN_X * scale)
    # Header block
    draw.rectangle([(0, 0), (int(CANVAS_W * scale), hdr_h)], outline=(0, 0, 0), width=1)
    _draw_mjcet_header(draw, scale)
    # Vertical margin line
    draw.line(
        [(mgn_x, hdr_h), (mgn_x, int(CANVAS_H * scale) - 30)],
        fill=MARGIN_COLOR[:3], width=1,
    )
    # Ruled lines below header
    y = hdr_h + line_h
    while y < int(CANVAS_H * scale) - 30:
        draw.line([(mgn_x + 2, y), (int(CANVAS_W * scale) - 20, y)],
                  fill=RULE_COLOR[:3] + (60,), width=1)
        y += line_h


def _draw_mjcet_assignment_header(
    draw: ImageDraw.ImageDraw,
    scale: float = 1.0,
    page_num: int = 1,
) -> None:
    """Draw MJCET Assignment / Tutorial Sheet header bar.

    Layout (single compact bar, left-to-right):
      [MJCET]  [Assignment / Tutorial Sheet]  [Page No. ...............]
    """
    hdr_h = int(MJCET_ASSIGN_HEADER_H * scale)
    w = int(CANVAS_W * scale)

    # Fonts scaled to header height
    font_college = _load_font("Bold", max(10, int(18 * scale)))
    font_title   = _load_font("SemiBold", max(9, int(14 * scale)))
    font_label   = _load_font("Regular", max(8, int(11 * scale)))

    # Vertical center of the header bar
    cy = hdr_h // 2

    # ── Left: "MJCET" ──
    college_text = "MJCET"
    bbox = draw.textbbox((0, 0), college_text, font=font_college)
    tx_h = bbox[3] - bbox[1]
    draw.text((int(30 * scale), cy - tx_h // 2), college_text,
              font=font_college, fill=(0, 0, 0))

    # ── Center: "Assignment / Tutorial Sheet" ──
    title_text = "Assignment / Tutorial Sheet"
    bbox = draw.textbbox((0, 0), title_text, font=font_title)
    tx_w = bbox[2] - bbox[0]
    tx_h = bbox[3] - bbox[1]
    draw.text(((w - tx_w) // 2, cy - tx_h // 2), title_text,
              font=font_title, fill=(0, 0, 0))

    # ── Right: "Page No." + dotted line ──
    page_text = f"Page No. ............................."
    bbox = draw.textbbox((0, 0), page_text, font=font_label)
    tx_w = bbox[2] - bbox[0]
    tx_h = bbox[3] - bbox[1]
    draw.text((w - tx_w - int(25 * scale), cy - tx_h // 2), page_text,
              font=font_label, fill=(0, 0, 0))

    # Bottom border of header bar
    draw.line([(0, hdr_h), (w, hdr_h)], fill=(0, 0, 0), width=max(1, int(2 * scale)))


def _draw_mjcet_assignment_template(
    draw: ImageDraw.ImageDraw,
    line_h: int,
    scale: float = 1.0,
    page_num: int = 1,
) -> None:
    """Draw MJCET Assignment / Tutorial Sheet template.

    Single compact header bar + red margin line + ruled body area.
    """
    hdr_h = int(MJCET_ASSIGN_HEADER_H * scale)
    mgn_x = int(MJCET_MARGIN_X * scale)
    w = int(CANVAS_W * scale)
    h = int(CANVAS_H * scale)

    # Header bar
    _draw_mjcet_assignment_header(draw, scale, page_num)

    # Vertical margin line (red/pink, from header bottom to near page bottom)
    draw.line(
        [(mgn_x, hdr_h + int(5 * scale)), (mgn_x, h - int(25 * scale))],
        fill=MARGIN_COLOR[:3], width=1,
    )

    # Ruled lines across body area (from margin line to right edge)
    y = hdr_h + line_h
    while y < h - int(25 * scale):
        draw.line(
            [(mgn_x + int(2 * scale), y), (w - int(15 * scale), y)],
            fill=RULE_COLOR[:3] + (60,), width=1,
        )
        y += line_h


def _new_canvas(settings: StyleSettings, line_h: int, page_num: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    bg_rgb = _hex_to_rgb(settings.bg_color)
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (*bg_rgb, 255))
    draw = ImageDraw.Draw(img)

    tmpl = settings.paper_template
    if tmpl == "ruled":
        _draw_ruled_lines(draw, line_h, settings.margin_top)
    elif tmpl == "grid":
        _draw_grid(draw, line_h)
    elif tmpl == "mjcet":
        _draw_mjcet_template(draw, line_h)
    elif tmpl == "mjcet_assignment":
        _draw_mjcet_assignment_template(draw, line_h, page_num=page_num)
    # "plain" → no template marks

    return img, draw


# ── Scanner post-processing ───────────────────────────────────────────────────


# ── Scanner caches (built once per unique canvas size, reused across pages) ───
# These sit at module level so multi-page exports pay the build cost only once.
_SCANNER_CACHE: dict[tuple[int, int], dict] = {}

def _get_scanner_cache(h: int, w: int) -> dict:
    """Return (or build) pre-computed grain, LUTs, and vignette for (h, w)."""
    key = (h, w)
    if key not in _SCANNER_CACHE:
        rng = np.random.default_rng(7)
        grain_half = rng.integers(240, 256, size=((h + 1) // 2, (w + 1) // 2), dtype=np.uint8)
        grain = np.repeat(np.repeat(grain_half, 2, axis=0), 2, axis=1)[:h, :w]

        lut_r = np.clip(np.arange(256, dtype=np.float32) * 1.008, 0, 255).astype(np.uint8)
        lut_b = np.clip(np.arange(256, dtype=np.float32) * 0.996, 0, 255).astype(np.uint8)

        # uint8 vignette factor (235..255) for uint16 fixed-point multiply
        y_idx, x_idx = np.ogrid[:h, :w]
        vf = np.clip(
            1.0 - 0.04 * ((x_idx - w / 2.0) ** 2 / (w / 2.0) ** 2
                         + (y_idx - h / 2.0) ** 2 / (h / 2.0) ** 2),
            0.92, 1.0,
        )
        vig = (vf * 255).astype(np.uint8)
        _SCANNER_CACHE[key] = {"grain": grain, "lut_r": lut_r, "lut_b": lut_b, "vig": vig}
    return _SCANNER_CACHE[key]


def _apply_scanner_effect(img: Image.Image) -> Image.Image:
    """Adds paper grain, elliptical vignette, and a gentle warmth shift.

    All expensive arrays (grain, vignette, LUTs) are pre-computed once per
    canvas size and cached at module level, so multi-page exports pay the
    build cost only on the first page.

    Typical hot-path: ~30-40ms per page (uint16 fixed-point, no float32 alloc).
    """
    arr = np.array(img.convert("RGB"))          # uint8 H×W×3
    h, w = arr.shape[:2]
    c = _get_scanner_cache(h, w)

    # Grain blend: 96% image + 4% grain — in uint16 to avoid overflow
    blended = (
        arr.astype(np.uint16) * 246 + c["grain"][:, :, None].astype(np.uint16) * 10
    ) >> 8                                       # >> 8  ≈  ÷256
    blended = blended.astype(np.uint8)

    # Warmth shift via LUT (O(256) not O(H×W))
    blended[:, :, 0] = c["lut_r"][blended[:, :, 0]]
    blended[:, :, 2] = c["lut_b"][blended[:, :, 2]]

    # Vignette: (pixel × vig_factor) >> 8, all in uint16
    out = (blended.astype(np.uint16) * c["vig"][:, :, None] >> 8).astype(np.uint8)

    return Image.fromarray(out).convert("RGBA")


# ── Core renderer ─────────────────────────────────────────────────────────────

def render(
    nodes: list[DocumentNode],
    settings: StyleSettings,
    low_res: bool = False,
    seed: int = 42,
) -> RenderResult:
    """
    Render a list of DocumentNodes onto A4 canvases.

    low_res=True  → 50% scale, simplified noise, JPEG output (preview path)
    low_res=False → full scale, full noise pipeline (export path)
    """
    t0 = time.perf_counter()

    scale = 0.5 if low_res else 1.0
    w = int(CANVAS_W * scale)
    h = int(CANVAS_H * scale)

    noise_cfg = make_noise_config(settings, seed=seed)
    if low_res:
        # Simplified noise for preview
        noise_cfg.rotation_jitter    = noise_cfg.rotation_jitter * 0.3
        noise_cfg.pressure_variance  = noise_cfg.pressure_variance * 0.3
        noise_cfg.enable_blur        = False
    noise_engine = HumanVariabilityEngine(noise_cfg)

    font_size   = max(10, int(settings.font_size * scale))
    line_h      = max(12, int(font_size * settings.line_spacing))
    margin_top  = int(settings.margin_top  * scale)
    # Auto-adjust margin_top so text never overlaps the assignment header
    if settings.paper_template == "mjcet_assignment":
        margin_top = max(margin_top, int((MJCET_ASSIGN_HEADER_H + 12) * scale))
    margin_left = int(settings.margin_left * scale)
    margin_right= int(settings.margin_right * scale)
    margin_bot  = int(settings.margin_bottom * scale)
    text_w      = w - margin_left - margin_right
    lines_per_page = max(1, (h - margin_top - margin_bot) // line_h)

    pages_images: list[Image.Image] = []

    # We render to a full-size scaled canvas first
    img, draw = _new_canvas_scaled(settings, line_h, w, h, len(pages_images))

    y = margin_top

    def flush_page():
        nonlocal img, draw, y
        pages_images.append(img)
        img, draw = _new_canvas_scaled(settings, line_h, w, h, len(pages_images))
        y = margin_top

    for node in nodes:
        if node.kind == "blank":
            y += int(line_h * 0.5)
            if y >= h - margin_bot:
                flush_page()
            continue

        # Image node
        if node.kind == "image" and node.image_bytes:
            try:
                diagram = Image.open(io.BytesIO(node.image_bytes)).convert("RGBA")
                max_w = text_w
                scale_f = min(1.0, max_w / diagram.width)
                new_w = int(diagram.width * scale_f)
                new_h = int(diagram.height * scale_f)
                diagram = diagram.resize((new_w, new_h), Image.LANCZOS)
                if y + new_h > h - margin_bot:
                    flush_page()
                img.paste(diagram, (margin_left, y), diagram)
                y += new_h + int(line_h * 0.5)
            except Exception:
                pass
            continue

        font, ink = _get_node_font_scaled(node, settings, scale)
        ink_rgb = _hex_to_rgb(ink)
        is_heading = node.kind in ("heading1", "heading2")

        # Prefix for list items
        prefix = "  •  " if node.kind == "list_item" else ""
        text_content = prefix + node.content

        # Extra spacing before headings
        if is_heading and y > margin_top:
            y += int(line_h * 0.4)

        wrapped = _wrap_text(text_content, font, text_w, draw)

        for line_text in wrapped:
            if y + line_h > h - margin_bot:
                flush_page()

            if not line_text:
                y += int(line_h * 0.4)
                continue

            # Render word-by-word so we can apply per-word noise
            x = margin_left
            words = line_text.split(" ")
            for word_idx, word in enumerate(words):
                if not word:
                    continue

                # Measure word width
                bbox = draw.textbbox((0, 0), word, font=font)
                word_w = bbox[2] - bbox[0]
                word_h = bbox[3] - bbox[1]

                # If word overflows line, wrap (safety)
                if x + word_w > w - margin_right and x > margin_left:
                    y += line_h
                    x = margin_left
                    if y + line_h > h - margin_bot:
                        flush_page()
                        y = margin_top

                # Baseline jitter
                jitter_y = noise_engine.baseline_offset() if not low_res else 0
                draw_y   = y + jitter_y

                # Render character-by-character for glyph transforms only in full mode
                if not low_res and noise_cfg.rotation_jitter > 0.01:
                    _render_word_with_noise(
                        img, draw, word, font, ink_rgb,
                        x, draw_y, noise_engine, is_heading
                    )
                else:
                    draw.text((x, draw_y), word, font=font, fill=ink_rgb)

                x += word_w
                # Word spacing
                space_w_bbox = draw.textbbox((0, 0), " ", font=font)
                base_space = space_w_bbox[2] - space_w_bbox[0]
                x += noise_engine.word_spacing_offset(base_space)
                noise_engine.next_word()

            y += line_h

        # Extra spacing after headings
        if is_heading:
            y += int(line_h * 0.2)

    # Don't forget last page
    if len(pages_images) == 0 or img is not pages_images[-1]:
        pages_images.append(img)

    # Post-processing
    results_b64: list[str] = []
    for pg in pages_images:
        if settings.enable_scanner_effect and not low_res:
            pg = _apply_scanner_effect(pg)

        # Whole-page slant (simulates paper misalignment in scanner)
        if abs(settings.page_slant_deg) > 0.01 and not low_res:
            bg_rgb = _hex_to_rgb(settings.bg_color)
            pg = pg.rotate(
                settings.page_slant_deg,
                expand=False,
                resample=Image.BICUBIC,
                fillcolor=(*bg_rgb, 255),
            )

        pg_rgb = pg.convert("RGB")

        if low_res:
            buf = io.BytesIO()
            pg_rgb.save(buf, format="JPEG", quality=78, optimize=True)
        else:
            buf = io.BytesIO()
            pg_rgb.save(buf, format="PNG", optimize=False)

        results_b64.append(base64.b64encode(buf.getvalue()).decode())

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return RenderResult(
        images_b64=results_b64,
        pages=len(results_b64),
        width=w,
        height=h,
        render_ms=elapsed_ms,
    )


def _new_canvas_scaled(
    settings: StyleSettings, line_h: int, w: int, h: int, page_num: int
) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    bg_rgb = _hex_to_rgb(settings.bg_color)
    img = Image.new("RGBA", (w, h), (*bg_rgb, 255))
    draw = ImageDraw.Draw(img)

    tmpl = settings.paper_template
    scale = w / CANVAS_W
    margin_top  = int(settings.margin_top  * scale)

    if tmpl == "ruled":
        y = margin_top
        while y < h - 20:
            draw.line([(0, y), (w, y)], fill=(180, 200, 220), width=1)
            y += line_h
    elif tmpl == "grid":
        y = 0
        while y < h:
            draw.line([(0, y), (w, y)], fill=(200, 210, 200), width=1)
            y += line_h
        x = 0
        while x < w:
            draw.line([(x, 0), (x, h)], fill=(200, 210, 200), width=1)
            x += line_h
    elif tmpl == "mjcet":
        _draw_mjcet_template(draw, line_h, scale)
    elif tmpl == "mjcet_assignment":
        _draw_mjcet_assignment_template(draw, line_h, scale, page_num=page_num)

    return img, draw


def _get_node_font_scaled(
    node: DocumentNode, settings: StyleSettings, scale: float
) -> tuple[ImageFont.FreeTypeFont, str]:
    size = max(10, int(settings.font_size * scale))
    if node.kind == "heading1":
        return _load_font("Bold", size + int(8 * scale)), settings.ink_color
    elif node.kind == "heading2":
        return _load_font("SemiBold", size + int(3 * scale)), settings.ink_color
    else:
        return _load_font(settings.font_variant, size), settings.ink_color


def _render_word_with_noise(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    word: str,
    font: ImageFont.FreeTypeFont,
    ink_rgb: tuple[int, int, int],
    x: int,
    y: int,
    noise: HumanVariabilityEngine,
    is_heading: bool,
) -> None:
    """Render a word character-by-character applying glyph-level transforms."""
    cx = x
    for ch_idx, char in enumerate(word):
        # Measure char
        bbox = draw.textbbox((0, 0), char, font=font)
        ch_w = bbox[2] - bbox[0]
        ch_h = bbox[3] - bbox[1]
        if ch_w <= 0:
            continue

        # Render char to a small patch
        pad = 6
        patch_w = ch_w + pad * 2
        patch_h = ch_h + pad * 2
        patch = Image.new("RGBA", (patch_w, patch_h), (0, 0, 0, 0))
        patch_draw = ImageDraw.Draw(patch)
        patch_draw.text((pad - bbox[0], pad - bbox[1]), char, font=font, fill=(*ink_rgb, 255))

        # Apply noise transforms
        patch = noise.apply_glyph_transforms(patch, is_heading=is_heading)

        # Paste back with alpha compositing
        paste_x = cx - pad
        paste_y = y - pad
        img.paste(patch, (paste_x, paste_y), patch)

        cx += ch_w
