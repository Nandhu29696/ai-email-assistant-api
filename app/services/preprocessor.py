"""
Email preprocessing service.
Removes HTML, signatures, reply-thread quotes, and normalises whitespace.
"""
import re
from bs4 import BeautifulSoup


# Common signature delimiters
_SIGNATURE_PATTERNS = [
    r"^--\s*$",
    r"^_{3,}\s*$",
    r"^(Best regards?|Kind regards?|Sincerely|Thanks?|Thank you|Cheers|Regards?),?\s*$",
    r"^Sent from my (iPhone|Android|iPad|Samsung|Galaxy)",
    r"^Get Outlook for",
    r"^This email (was sent|is confidential)",
]
_SIG_RE = re.compile("|".join(_SIGNATURE_PATTERNS), re.IGNORECASE | re.MULTILINE)

# Reply-thread separator patterns
_THREAD_PATTERNS = [
    r"^-{3,} ?Original Message ?-{3,}",
    r"^On .+ wrote:",
    r"^From: .+\nSent: .+\nTo: .+",
    r"^>{1,}",  # quoted lines
]
_THREAD_RE = re.compile("|".join(_THREAD_PATTERNS), re.IGNORECASE | re.MULTILINE)


def strip_html(html: str) -> str:
    """Convert HTML email body to plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # Remove script, style, head elements
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    return text


def remove_signature(text: str) -> str:
    """Truncate text at the first signature delimiter found in the lower section of the message."""
    if not text:
        return ""
    lines = text.splitlines()
    total_lines = len(lines)
    # Don't strip signatures if email is very short or if pattern occurs in header/top lines
    start_search_idx = max(2, int(total_lines * 0.35)) if total_lines > 4 else 2

    for i in range(start_search_idx, total_lines):
        line = lines[i].strip()
        if _SIG_RE.match(line):
            candidate = "\n".join(lines[:i]).strip()
            if len(candidate) >= 15:
                return candidate
    return text


def remove_thread_quotes(text: str) -> str:
    """Remove reply-thread quoted content."""
    # Split on thread separators and keep only the first part
    parts = _THREAD_RE.split(text, maxsplit=1)
    return parts[0].strip() if parts else text


def normalise_whitespace(text: str) -> str:
    """Collapse excessive blank lines and trim."""
    # Replace 3+ consecutive newlines with two
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing whitespace on each line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


def preprocess_email(body_plain: str | None, body_html: str | None) -> str:
    """
    Full preprocessing pipeline.
    Returns a clean plain-text body suitable for NLP analysis.
    """
    if body_html:
        text = strip_html(body_html)
    elif body_plain:
        text = body_plain
    else:
        return ""

    text = remove_thread_quotes(text)
    text = remove_signature(text)
    text = normalise_whitespace(text)
    return text
