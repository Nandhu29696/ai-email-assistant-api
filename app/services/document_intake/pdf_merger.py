"""
PDF builder/merger (rules 5.2 and 5.3).

``build_email_pdf`` renders the email itself (headers, attachment list, body)
as a PDF; ``merge_pdfs`` joins the converted attachments in their original
order with the email PDF as the last document.
"""
from __future__ import annotations
import io
from dataclasses import dataclass, field


@dataclass
class EmailMetadataForTrailer:
    from_email: str
    to_email: str
    subject: str
    body: str
    received_datetime: str
    attachments: list[str] = field(default_factory=list)
    batch_no: str = ""
    summary: str = ""


_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",   # Debian/Ubuntu (fonts-dejavu-core)
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
)
_font_name: str | None = None


def _unicode_font() -> str:
    """Register a TrueType font that covers non-Latin text; fall back to Helvetica."""
    global _font_name
    if _font_name:
        return _font_name
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("TrailerUnicode", path))
                _font_name = "TrailerUnicode"
                return _font_name
            except Exception:
                continue
    _font_name = "Helvetica"
    return _font_name


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines: list[str] = []
    for raw_line in (text or "").splitlines() or [""]:
        current = ""
        for word in raw_line.split(" "):
            candidate = f"{current} {word}" if current else word
            if stringWidth(candidate, font, size) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            # Hard-break words longer than the line.
            while stringWidth(word, font, size) > max_width and len(word) > 1:
                cut = len(word)
                while cut > 1 and stringWidth(word[:cut], font, size) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


def build_email_pdf(meta: EmailMetadataForTrailer) -> bytes:
    """Render the email content as a PDF (one or more pages)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    font = _unicode_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Email - {meta.subject or 'no subject'}"[:200])
    width, height = A4
    left = 0.75 * inch
    usable = width - 2 * left
    line_height = 0.22 * inch
    y = height - 1 * inch

    def write(line: str, size: float) -> None:
        nonlocal y
        if y < 0.75 * inch:
            c.showPage()
            y = height - 1 * inch
        c.setFont(font, size)
        c.drawString(left, y, line)
        y -= line_height

    write("Email content", 14)
    y -= line_height * 0.5
    rows = [
        ("From", meta.from_email),
        ("To", meta.to_email),
        ("Subject", meta.subject),
        ("Received", meta.received_datetime),
    ]
    if meta.batch_no:
        rows.append(("Reference", meta.batch_no))
    if meta.attachments:
        rows.append(("Attachments", ", ".join(meta.attachments)))
    for label, value in rows:
        for line in _wrap(f"{label}: {value or '-'}", font, 10, usable):
            write(line, 10)

    if meta.summary:
        y -= line_height * 0.5
        write("Summary:", 10)
        for line in _wrap(meta.summary, font, 9, usable):
            write(line, 9)

    y -= line_height * 0.5
    write("Message:", 10)
    for line in _wrap(meta.body or "(empty)", font, 9, usable):
        write(line, 9)

    c.save()
    return buf.getvalue()


def merge_pdfs(pdfs: list[bytes]) -> bytes:
    """Concatenate PDFs in the given order."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for pdf_bytes in pdfs:
        for page in PdfReader(io.BytesIO(pdf_bytes)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def merge_pdfs_with_trailer(converted_pdfs: list[bytes], email_meta: EmailMetadataForTrailer) -> bytes:
    """Attachments in their original order, then the email-content PDF as the last pages."""
    return merge_pdfs([*converted_pdfs, build_email_pdf(email_meta)])
