"""DOC/DOCX -> PDF converter (§5 step 8) using LibreOffice headless (cross-platform, license-free)."""
from __future__ import annotations
import subprocess
import tempfile
import os
from loguru import logger
from app.config import settings


class DocConversionError(Exception):
    pass


def convert_doc_to_pdf(data: bytes, original_filename: str) -> bytes:
    """
    Convert a .doc/.docx byte stream to PDF using `soffice --headless --convert-to pdf`.
    Requires LibreOffice installed and available at settings.LIBREOFFICE_BIN_PATH.
    """
    suffix = "." + original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ".docx"

    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, f"input{suffix}")
        with open(src_path, "wb") as f:
            f.write(data)

        try:
            result = subprocess.run(
                [
                    settings.LIBREOFFICE_BIN_PATH,
                    "--headless", "--norestore",
                    "--convert-to", "pdf",
                    "--outdir", tmp_dir,
                    src_path,
                ],
                capture_output=True,
                timeout=90,
                check=False,
            )
        except FileNotFoundError as exc:
            raise DocConversionError(f"LibreOffice binary not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocConversionError(f"LibreOffice conversion timed out: {exc}") from exc

        out_path = os.path.join(tmp_dir, "input.pdf")
        if result.returncode != 0 or not os.path.exists(out_path):
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            logger.error(f"[doc_to_pdf] LibreOffice conversion failed: {stderr}")
            raise DocConversionError(f"LibreOffice conversion failed: {stderr[:300]}")

        with open(out_path, "rb") as f:
            return f.read()
