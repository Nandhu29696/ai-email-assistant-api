"""TIFF/TIF -> PDF converter (§5 step 8) using Pillow."""
from __future__ import annotations
import io


def convert_tiff_to_pdf(data: bytes) -> bytes:
    """Convert a (possibly multi-page) TIFF image to a PDF."""
    from PIL import Image, ImageSequence

    img = Image.open(io.BytesIO(data))
    # Guard against decompression bombs (Pillow raises above its pixel limit).
    if img.width * img.height > 200_000_000:
        raise ValueError("TIFF image is too large to convert")
    pages = []
    for frame in ImageSequence.Iterator(img):
        pages.append(frame.convert("RGB"))

    if not pages:
        raise ValueError("TIFF file contains no readable frames")

    out = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(out, format="PDF", save_all=True, append_images=rest)
    return out.getvalue()
