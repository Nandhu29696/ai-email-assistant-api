"""DOC/DOCX -> PDF converter using LibreOffice headless (cross-platform, license-free)."""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from loguru import logger
from app.config import settings


class DocConversionError(Exception):
    """The document could not be converted (damaged or unsupported content)."""


class ConverterUnavailableError(DocConversionError):
    """LibreOffice is not installed/reachable — a system problem, not the sender's fault."""


_COMMON_LOCATIONS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
)


@lru_cache(maxsize=1)
def find_soffice() -> str | None:
    """Locate LibreOffice: the configured binary, the PATH, then the usual install folders."""
    configured = settings.LIBREOFFICE_BIN_PATH or "soffice"
    if os.path.isfile(configured):
        return configured
    found = shutil.which(configured) or shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    return next((path for path in _COMMON_LOCATIONS if os.path.isfile(path)), None)


def converter_status() -> tuple[bool, str]:
    binary = find_soffice()
    if binary:
        return True, binary
    return False, "LibreOffice is not installed (needed to convert Word files to PDF)"


def convert_doc_to_pdf(data: bytes, original_filename: str) -> bytes:
    """Convert a .doc/.docx byte stream to PDF with ``soffice --headless --convert-to pdf``."""
    binary = find_soffice()
    if not binary:
        raise ConverterUnavailableError("LibreOffice is not installed")
    suffix = "." + original_filename.rsplit(".", 1)[-1].lower() if "." in original_filename else ".docx"

    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = os.path.join(tmp_dir, f"input{suffix}")
        with open(src_path, "wb") as f:
            f.write(data)

        try:
            result = subprocess.run(
                [
                    binary,
                    # A private profile per run: concurrent soffice processes
                    # sharing the default profile fail or serialize.
                    f"-env:UserInstallation={Path(tmp_dir, 'lo_profile').as_uri()}",
                    "--headless", "--norestore", "--nolockcheck",
                    "--convert-to", "pdf",
                    "--outdir", tmp_dir,
                    src_path,
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except FileNotFoundError as exc:
            find_soffice.cache_clear()
            raise ConverterUnavailableError(f"LibreOffice binary not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocConversionError("Conversion timed out") from exc

        out_path = os.path.join(tmp_dir, "input.pdf")
        if result.returncode != 0 or not os.path.exists(out_path):
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            logger.warning(f"[doc_to_pdf] LibreOffice could not convert {original_filename}: {stderr[:300]}")
            raise DocConversionError("The document could not be opened for conversion")

        with open(out_path, "rb") as f:
            return f.read()
