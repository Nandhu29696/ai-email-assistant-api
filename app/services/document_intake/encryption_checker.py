"""
Password/encryption detector for the document-intake pipeline (§5 step 7).
Checks PDFs via pypdf and Office docs (.doc/.docx) via msoffcrypto-tool
*before* any conversion is attempted.
"""
from __future__ import annotations
import io
from dataclasses import dataclass
from loguru import logger


@dataclass
class EncryptionCheckResult:
    is_encrypted: bool
    reason: str


def _check_pdf(data: bytes) -> EncryptionCheckResult:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Owner-password-only PDFs (print/copy restrictions) open with an
            # empty user password and can be processed normally.
            try:
                if reader.decrypt(""):
                    return EncryptionCheckResult(is_encrypted=False, reason="OK (permission-restricted PDF)")
            except Exception:
                pass
            return EncryptionCheckResult(is_encrypted=True, reason="PDF is password-protected/encrypted")
        return EncryptionCheckResult(is_encrypted=False, reason="OK")
    except Exception as exc:
        # A corrupt PDF is not an encrypted one; let conversion report it as a failure.
        logger.warning(f"[encryption_checker] PDF structure unreadable: {exc}")
        return EncryptionCheckResult(is_encrypted=False, reason=f"Unreadable PDF: {exc}")


def _check_office_doc(data: bytes) -> EncryptionCheckResult:
    try:
        import msoffcrypto
        file_obj = io.BytesIO(data)
        office_file = msoffcrypto.OfficeFile(file_obj)
        if office_file.is_encrypted():
            return EncryptionCheckResult(is_encrypted=True, reason="Office document is password-protected/encrypted")
        return EncryptionCheckResult(is_encrypted=False, reason="OK")
    except Exception as exc:
        # msoffcrypto raises on plain (non-OLE) modern .docx that aren't encrypted — treat as not encrypted.
        logger.debug(f"[encryption_checker] Office doc check inconclusive (assuming not encrypted): {exc}")
        return EncryptionCheckResult(is_encrypted=False, reason="OK")


def check_encryption(filename: str, data: bytes) -> EncryptionCheckResult:
    """Dispatch encryption check by file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _check_pdf(data)
    if ext in ("doc", "docx"):
        return _check_office_doc(data)

    # TIFF and other formats: no standard encryption mechanism to check.
    return EncryptionCheckResult(is_encrypted=False, reason="OK")
