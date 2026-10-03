"""
Attachment readability check (rule 4).

Every attachment with an allowed extension is opened before anything is
converted. Files that are password-protected/encrypted or that cannot be read
(damaged, empty, wrong content for the extension) are reported back to the
sender in one reply.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from loguru import logger

OK = "OK"
PROTECTED = "PROTECTED"
UNREADABLE = "UNREADABLE"

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_MAGIC = b"PK\x03\x04"


@dataclass
class AttachmentCheck:
    status: str      # OK | PROTECTED | UNREADABLE
    reason: str

    @property
    def ok(self) -> bool:
        return self.status == OK


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _check_pdf(data: bytes) -> AttachmentCheck:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Owner-password-only PDFs (print/copy restrictions) open with an empty password.
            try:
                opened = bool(reader.decrypt(""))
            except Exception:
                opened = False
            if not opened:
                return AttachmentCheck(PROTECTED, "The PDF is password-protected")
        if len(reader.pages) == 0:
            return AttachmentCheck(UNREADABLE, "The PDF has no pages")
        for page in reader.pages:
            page.get_contents()
            _ = page.mediabox
        return AttachmentCheck(OK, "OK")
    except Exception as exc:
        logger.info(f"[attachment_validator] PDF unreadable: {exc}")
        return AttachmentCheck(UNREADABLE, "The PDF is damaged or not a valid PDF file")


def _ole_is_encrypted(data: bytes) -> bool:
    import msoffcrypto

    try:
        return bool(msoffcrypto.OfficeFile(io.BytesIO(data)).is_encrypted())
    except Exception as exc:
        logger.debug(f"[attachment_validator] Office encryption check inconclusive: {exc}")
        return False


def _check_word(data: bytes) -> AttachmentCheck:
    # Password-protected .docx files are stored in an OLE container, like legacy .doc files.
    if data.startswith(_OLE_MAGIC):
        if _ole_is_encrypted(data):
            return AttachmentCheck(PROTECTED, "The Word document is password-protected")
        return AttachmentCheck(OK, "OK")
    if data.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" not in archive.namelist():
                    return AttachmentCheck(UNREADABLE, "The file is not a valid Word document")
                if archive.testzip() is not None:
                    return AttachmentCheck(UNREADABLE, "The Word document is damaged")
            return AttachmentCheck(OK, "OK")
        except zipfile.BadZipFile:
            return AttachmentCheck(UNREADABLE, "The Word document is damaged")
    if data.lstrip()[:5] == b"{\\rtf":
        return AttachmentCheck(OK, "OK")   # RTF saved with a .doc name; LibreOffice reads it
    return AttachmentCheck(UNREADABLE, "The file is not a valid Word document")


def _check_tiff(data: bytes) -> AttachmentCheck:
    from PIL import Image, ImageSequence

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 200_000_000:
                return AttachmentCheck(UNREADABLE, "The image is too large to process")
            frames = 0
            for frame in ImageSequence.Iterator(image):
                frame.load()
                frames += 1
            if frames == 0:
                return AttachmentCheck(UNREADABLE, "The image has no pages")
        return AttachmentCheck(OK, "OK")
    except Exception as exc:
        logger.info(f"[attachment_validator] TIFF unreadable: {exc}")
        return AttachmentCheck(UNREADABLE, "The image is damaged or not a valid TIFF file")


def check_attachment(filename: str, data: bytes) -> AttachmentCheck:
    """Can this attachment be opened? Only called for allowed extensions."""
    if not data:
        return AttachmentCheck(UNREADABLE, "The file is empty")
    ext = _extension(filename)
    if ext == "pdf":
        return _check_pdf(data)
    if ext in ("doc", "docx"):
        return _check_word(data)
    if ext in ("tif", "tiff"):
        return _check_tiff(data)
    return AttachmentCheck(UNREADABLE, f"Files of type .{ext or '?'} cannot be processed")
