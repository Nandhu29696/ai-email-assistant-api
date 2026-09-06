"""
Sensitive data (PII) detector for the document-intake pipeline (§1.2.2).
Two-tier strategy mirroring classifier.py's regex-first/LLM-fallback pattern.
"""
from __future__ import annotations
import re
import io
import zipfile
from dataclasses import dataclass, field
from app.config import settings
from app.services.ai_client import get_ai_client, get_model, ai_available


@dataclass
class SensitivityResult:
    sensitivity_level: str          # public | internal | confidential | restricted
    contains_pii: bool
    pii_types: list[str] = field(default_factory=list)
    confidence: float = 0.0


# ── Tier 1: deterministic regex patterns ──────────────────────
_PII_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "passport": re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),
}


def _luhn_valid(card_number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", card_number)]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _tier1_scan(text: str) -> tuple[bool, list[str]]:
    found_types: list[str] = []

    for pii_type, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(text)
        if not matches:
            continue
        if pii_type == "credit_card":
            if any(_luhn_valid(m) for m in matches):
                found_types.append(pii_type)
        else:
            found_types.append(pii_type)

    return (len(found_types) > 0, found_types)


async def _tier2_llm_scan(text: str) -> SensitivityResult | None:
    """Optional LLM-based contextual sensitivity classification."""
    if not ai_available():
        return None
    try:
        client = get_ai_client()
        prompt = (
            "Classify the sensitivity of the following document/email text.\n"
            "Respond with ONLY a JSON object like:\n"
            '{"sensitivity_level": "confidential", "contains_pii": true, '
            '"pii_types": ["financial"], "confidence": 0.85}\n\n'
            "sensitivity_level must be one of: public, internal, confidential, restricted.\n\n"
            f"Text:\n{text[:2000]}"
        )
        response = await client.chat.completions.create(
            model=get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=100,
        )
        import json
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
        data = json.loads(content)
        return SensitivityResult(
            sensitivity_level=data.get("sensitivity_level", "internal"),
            contains_pii=bool(data.get("contains_pii", False)),
            pii_types=list(data.get("pii_types", [])),
            confidence=float(data.get("confidence", 0.5)),
        )
    except Exception:
        return None


async def detect_sensitivity(text: str) -> SensitivityResult:
    """
    Run Tier-1 regex scan (always), then optionally Tier-2 LLM scan when
    Tier-1 finds nothing conclusive or AI_SENSITIVITY_DEEP_SCAN=True.
    """
    if not text or not text.strip():
        return SensitivityResult(sensitivity_level="public", contains_pii=False, pii_types=[], confidence=1.0)

    contains_pii, pii_types = _tier1_scan(text)

    if contains_pii:
        level = "restricted" if any(t in pii_types for t in ("ssn", "credit_card", "passport", "iban")) else "confidential"
        result = SensitivityResult(sensitivity_level=level, contains_pii=True, pii_types=pii_types, confidence=0.9)
    else:
        result = SensitivityResult(sensitivity_level="internal", contains_pii=False, pii_types=[], confidence=0.6)

    if settings.AI_SENSITIVITY_DEEP_SCAN:
        llm_result = await _tier2_llm_scan(text)
        if llm_result is not None:
            return llm_result

    return result


def extract_attachment_text(filename: str, data: bytes) -> str:
    """Extract searchable text from supported attachment formats before sensitivity scanning.

    TIFF uses pytesseract when the Tesseract runtime is available; if OCR is
    unavailable the pipeline records and processes the attachment normally.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if extension == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""

    if extension == "docx":
        try:
            from xml.etree import ElementTree
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml_data = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml_data)
            return " ".join(node.text or "" for node in root.iter() if node.text)
        except Exception:
            return ""

    if extension in ("tif", "tiff"):
        try:
            from PIL import Image
            import pytesseract
            return pytesseract.image_to_string(Image.open(io.BytesIO(data)))
        except Exception:
            return ""

    return ""
