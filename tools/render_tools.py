"""Render tools — convert structured data into downloadable files.

These tools contain no AI logic.  AI logic lives in the Agent's tool-use loop
managed by the LLM.  Tools only: accept structured input → render file → upload → return URL.
"""

from __future__ import annotations

import re
import tempfile
import uuid
from pathlib import Path

from config.settings import get_settings


# ── PPT Generation ──────────────────────────────────────────────


async def generate_pptx(
    slides: list[dict],
    title: str = "Presentation",
    template: str = "default",
) -> dict:
    """Generate a PowerPoint file from structured slides JSON and return a download link.

    Args:
        slides: List of slide dicts, each with layout/title/body/notes fields.
            layout options: "title", "content", "two_column".
        title: Presentation title.
        template: Template name (default/education/minimal).

    Returns:
        {"url": "...", "filename": "xxx.pptx", "slide_count": N, "size": bytes}
    """
    from pptx import Presentation

    prs = Presentation()

    for slide_data in slides:
        layout_name = slide_data.get("layout", "content")

        if layout_name == "title":
            slide_layout = prs.slide_layouts[0]  # Title Slide
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = slide_data.get("title", "")
            if len(slide.placeholders) > 1:
                slide.placeholders[1].text = slide_data.get("body", "")

        elif layout_name == "two_column":
            slide_layout = prs.slide_layouts[3]  # Two Content
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = slide_data.get("title", "")
            if len(slide.placeholders) > 1:
                slide.placeholders[1].text = slide_data.get("left", "")
            if len(slide.placeholders) > 2:
                slide.placeholders[2].text = slide_data.get("right", "")

        else:  # "content" or default
            slide_layout = prs.slide_layouts[1]  # Title and Content
            slide = prs.slides.add_slide(slide_layout)
            slide.shapes.title.text = slide_data.get("title", "")
            if len(slide.placeholders) > 1:
                body = slide_data.get("body", "")
                tf = slide.placeholders[1].text_frame
                tf.clear()
                for i, line in enumerate(body.split("\n")):
                    if i == 0:
                        tf.paragraphs[0].text = line.strip()
                    else:
                        p = tf.add_paragraph()
                        p.text = line.strip()

        # Speaker notes
        if slide_data.get("notes"):
            notes_slide = slide.notes_slide
            notes_slide.notes_text_frame.text = slide_data["notes"]

    filename = f"{_safe_filename(title)}.pptx"
    filepath = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}_{filename}"
    prs.save(str(filepath))

    url = await _upload_file(
        filepath, filename,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )

    return {
        "url": url,
        "filename": filename,
        "slide_count": len(slides),
        "size": filepath.stat().st_size,
    }


# ── Word Document Generation ────────────────────────────────────


async def generate_docx(
    content: str,
    title: str = "Document",
    format: str = "plain",
) -> dict:
    """Generate a Word document from Markdown content.

    Args:
        content: Markdown-formatted document content.
        title: Document title.
        format: Template style (plain/lesson_plan/worksheet/report).

    Returns:
        {"url": "...", "filename": "xxx.docx", "size": bytes}
    """
    from docx import Document

    doc = Document()
    doc.add_heading(title, 0)

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif len(line) > 2 and line[0].isdigit() and line[1] == ".":
            doc.add_paragraph(line[3:].strip(), style="List Number")
        elif line.startswith("> "):
            doc.add_paragraph(line[2:])
        elif line.startswith("---"):
            doc.add_page_break()
        else:
            doc.add_paragraph(line)

    filename = f"{_safe_filename(title)}.docx"
    filepath = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}_{filename}"
    doc.save(str(filepath))

    url = await _upload_file(
        filepath, filename,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    return {
        "url": url,
        "filename": filename,
        "size": filepath.stat().st_size,
    }


# ── PDF Rendering ────────────────────────────────────────────────


async def render_pdf(
    html_content: str,
    title: str = "Document",
    css_template: str = "default",
) -> dict:
    """Render HTML content into a PDF file.

    Args:
        html_content: HTML string (can include inline CSS).
        title: File title.
        css_template: CSS template (default/worksheet/report).

    Returns:
        {"url": "...", "filename": "xxx.pdf", "size": bytes}
    """
    try:
        from weasyprint import HTML, CSS

        css = _get_css_template(css_template)

        full_html = (
            f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"<title>{title}</title></head>"
            f"<body>{html_content}</body></html>"
        )

        pdf_bytes = HTML(string=full_html).write_pdf(
            stylesheets=[CSS(string=css)]
        )
    except ImportError:
        # weasyprint not installed — fallback to returning HTML as-is
        pdf_bytes = html_content.encode("utf-8")

    filename = f"{_safe_filename(title)}.pdf"
    filepath = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}_{filename}"
    filepath.write_bytes(pdf_bytes)

    url = await _upload_file(filepath, filename, "application/pdf")

    return {
        "url": url,
        "filename": filename,
        "size": len(pdf_bytes),
    }


# ── Internal Helpers ─────────────────────────────────────────────


def _safe_filename(name: str) -> str:
    """Sanitize a filename."""
    clean = re.sub(r'[<>:"/\\|?*]', "", name)
    return clean[:100] or "untitled"


def _get_css_template(template: str) -> str:
    """Load a CSS template for PDF rendering."""
    templates = {
        "default": """
            body { font-family: 'Noto Sans SC', sans-serif; padding: 2cm; line-height: 1.6; }
            h1 { color: #1a1a1a; border-bottom: 2px solid #333; padding-bottom: 8px; }
            h2 { color: #333; margin-top: 1.5em; }
            table { border-collapse: collapse; width: 100%; margin: 1em 0; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background: #f5f5f5; }
        """,
        "worksheet": """
            body { font-family: 'Noto Sans SC', sans-serif; padding: 1.5cm; font-size: 14pt; }
            h1 { text-align: center; font-size: 20pt; }
            .question { margin: 1.5em 0; page-break-inside: avoid; }
            .answer-area { border: 1px dashed #ccc; min-height: 3cm; margin: 0.5em 0; }
        """,
        "report": """
            body { font-family: 'Noto Sans SC', sans-serif; padding: 2cm; }
            h1 { color: #1a56db; }
            .chart { text-align: center; margin: 1em 0; }
            .summary { background: #f0f4ff; padding: 1em; border-radius: 8px; }
        """,
    }
    return templates.get(template, templates["default"])


async def _upload_file(filepath: Path, filename: str, content_type: str) -> str:
    """Upload a file to storage.

    Tries Java backend OSS upload first; falls back to local path for development.
    """
    try:
        from services.java_client import get_client
        client = get_client()
        if client is not None:
            with open(filepath, "rb") as f:
                files = {"file": (filename, f, content_type)}
                response = await client.post(
                    "/api/files/upload",
                    files=files,
                    params={"purpose": "GENERATED_CONTENT"},
                )
                data = response.json()
                return data.get("data", {}).get("url", "")
    except Exception:
        pass

    # Fallback: return local path (development environment)
    return f"/api/files/generated/{filepath.name}"
    # Note: temporary file is NOT deleted here — caller or cleanup job handles it
