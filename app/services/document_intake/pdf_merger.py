"""
PDF merger (§5 step 8) — merges all converted attachment PDFs into one document
and appends a generated "Email Metadata" trailer page as the last page.
"""
from __future__ import annotations
import io
from dataclasses import dataclass


@dataclass
class EmailMetadataForTrailer:
    from_email: str
    to_email: str
    subject: str
    body: str
    received_datetime: str


def _build_trailer_page(meta: EmailMetadataForTrailer) -> bytes:
    """Generate a single-page PDF containing the source email's metadata."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.75 * inch, height - 1 * inch, "Email Metadata")

    c.setFont("Helvetica", 10)
    y = height - 1.5 * inch
    line_height = 0.28 * inch

    fields = [
        ("From", meta.from_email),
        ("To", meta.to_email),
        ("Subject", meta.subject),
        ("Received", meta.received_datetime),
    ]
    for label, value in fields:
        c.drawString(0.75 * inch, y, f"{label}: {value or '-'}")
        y -= line_height

    y -= line_height * 0.5
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.75 * inch, y, "Body:")
    y -= line_height

    c.setFont("Helvetica", 9)
    max_width_chars = 100
    body_text = meta.body or "(empty)"
    for raw_line in body_text.splitlines() or [""]:
        while len(raw_line) > max_width_chars:
            chunk, raw_line = raw_line[:max_width_chars], raw_line[max_width_chars:]
            c.drawString(0.75 * inch, y, chunk)
            y -= line_height
            if y < 0.75 * inch:
                c.showPage()
                c.setFont("Helvetica", 9)
                y = height - 1 * inch
        c.drawString(0.75 * inch, y, raw_line)
        y -= line_height
        if y < 0.75 * inch:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = height - 1 * inch

    c.save()
    return buf.getvalue()


def merge_pdfs_with_trailer(converted_pdfs: list[bytes], email_meta: EmailMetadataForTrailer) -> bytes:
    """
    Merge N converted attachment PDFs (in original order) and append the
    generated email-metadata page as the final page.
    """
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for pdf_bytes in converted_pdfs:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    trailer_bytes = _build_trailer_page(email_meta)
    trailer_reader = PdfReader(io.BytesIO(trailer_bytes))
    for page in trailer_reader.pages:
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
