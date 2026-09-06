"""PDF passthrough converter (§5 step 8) — validates/normalizes a PDF that is already a PDF."""
from __future__ import annotations
import io


def convert_pdf_passthrough(data: bytes) -> bytes:
    """
    Normalize a PDF attachment: re-serialize through pypdf so downstream
    merge operations receive a clean, consistent PDF object stream.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
