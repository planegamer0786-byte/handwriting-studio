"""
document_parser.py — Converts DOCX, PDF, or plain text into a
DocumentNode tree that the renderer can consume.
"""
from __future__ import annotations

import io
import re
from typing import Iterator

from models import DocumentNode


# ── Plain text ────────────────────────────────────────────────────────────────

def parse_plain_text(text: str) -> list[DocumentNode]:
    """
    Heuristically detect headings in plain text and build a node tree.

    Detection rules (applied in order):
      - ALL CAPS line ≤ 60 chars          → heading1
      - Line ending with ':' ≤ 60 chars   → heading2
      - Line starting with '- ' or '* '  → list_item
      - Empty line                        → blank
      - Everything else                   → paragraph
    """
    nodes: list[DocumentNode] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            nodes.append(DocumentNode(kind="blank"))
        elif stripped.upper() == stripped and len(stripped) <= 60 and len(stripped) > 3:
            nodes.append(DocumentNode(kind="heading1", content=stripped))
        elif stripped.endswith(":") and len(stripped) <= 60:
            nodes.append(DocumentNode(kind="heading2", content=stripped))
        elif stripped.startswith(("- ", "* ", "• ")):
            nodes.append(DocumentNode(kind="list_item", content=stripped[2:].strip()))
        else:
            nodes.append(DocumentNode(kind="paragraph", content=stripped))
    return nodes


# ── DOCX ──────────────────────────────────────────────────────────────────────

def parse_docx(file_bytes: bytes) -> list[DocumentNode]:
    """Parse a DOCX file into DocumentNodes preserving heading hierarchy."""
    try:
        import docx  # python-docx
    except ImportError:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")

    doc = docx.Document(io.BytesIO(file_bytes))
    nodes: list[DocumentNode] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            nodes.append(DocumentNode(kind="blank"))
            continue

        style_name = para.style.name.lower() if para.style else ""

        if "heading 1" in style_name:
            nodes.append(DocumentNode(kind="heading1", content=text))
        elif "heading 2" in style_name or "heading 3" in style_name:
            nodes.append(DocumentNode(kind="heading2", content=text))
        elif "list" in style_name:
            nodes.append(DocumentNode(kind="list_item", content=text))
        else:
            nodes.append(DocumentNode(kind="paragraph", content=text))

    return nodes


# ── PDF ───────────────────────────────────────────────────────────────────────

def parse_pdf(file_bytes: bytes) -> list[DocumentNode]:
    """
    Extract text from PDF using pdfplumber.
    Font-size heuristics are used to infer heading vs body.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")

    nodes: list[DocumentNode] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["size"])
            if not words:
                continue

            # Group words into lines by y-position (within 3px tolerance)
            lines: dict[int, list[dict]] = {}
            for w in words:
                y_bucket = int(w["top"] / 3) * 3
                lines.setdefault(y_bucket, []).append(w)

            # Estimate body font size as median
            sizes = sorted(float(w.get("size", 12)) for w in words)
            body_size = sizes[len(sizes) // 2] if sizes else 12.0

            for y_key in sorted(lines):
                line_words = sorted(lines[y_key], key=lambda w: w["x0"])
                line_text  = " ".join(w["text"] for w in line_words).strip()
                if not line_text:
                    nodes.append(DocumentNode(kind="blank"))
                    continue

                avg_size = sum(float(w.get("size", body_size)) for w in line_words) / len(line_words)

                if avg_size >= body_size * 1.35:
                    nodes.append(DocumentNode(kind="heading1", content=line_text))
                elif avg_size >= body_size * 1.15:
                    nodes.append(DocumentNode(kind="heading2", content=line_text))
                elif line_text.startswith(("- ", "• ", "* ")):
                    nodes.append(DocumentNode(kind="list_item", content=line_text[2:].strip()))
                else:
                    nodes.append(DocumentNode(kind="paragraph", content=line_text))

            nodes.append(DocumentNode(kind="blank"))  # page separator

    return nodes


# ── Router ────────────────────────────────────────────────────────────────────

def parse_document(file_bytes: bytes, mime_type: str) -> list[DocumentNode]:
    """Dispatch to the correct parser based on MIME type."""
    if "pdf" in mime_type:
        return parse_pdf(file_bytes)
    elif "wordprocessingml" in mime_type or mime_type.endswith("docx"):
        return parse_docx(file_bytes)
    else:
        return parse_plain_text(file_bytes.decode("utf-8", errors="replace"))


def nodes_to_plain_text(nodes: list[DocumentNode]) -> str:
    """Flatten a node tree back to plain text (for preview path)."""
    lines = []
    for n in nodes:
        if n.kind == "blank":
            lines.append("")
        elif n.kind in ("heading1", "heading2"):
            lines.append(n.content.upper() if n.kind == "heading1" else n.content)
        elif n.kind == "list_item":
            lines.append(f"  - {n.content}")
        else:
            lines.append(n.content)
    return "\n".join(lines)
