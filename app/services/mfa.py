"""TOTP (RFC 6238) multi-factor authentication helpers and recovery codes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

TOTP_PERIOD = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1          # accept codes from ±1 time step (clock drift)
RECOVERY_CODE_COUNT = 10


def generate_secret() -> str:
    """160-bit random secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** TOTP_DIGITS)
    return str(code).zfill(TOTP_DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // TOTP_PERIOD)


def totp(secret: str, step: int | None = None) -> str:
    return _hotp(secret, current_step() if step is None else step)


def verify_totp(secret: str, code: str, last_used_step: int | None = None, now: float | None = None) -> int | None:
    """Return the matched time step, or None. Rejects reuse of an already-used step."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != TOTP_DIGITS:
        return None
    step_now = current_step(now)
    for step in range(step_now - TOTP_WINDOW, step_now + TOTP_WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue  # replay protection
        if hmac.compare_digest(_hotp(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def generate_recovery_codes() -> tuple[list[str], list[str]]:
    """Return (plaintext codes to show once, hashes to store)."""
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(RECOVERY_CODE_COUNT)]
    return codes, [_hash_code(c) for c in codes]


def consume_recovery_code(stored_hashes: list[str] | None, code: str) -> list[str] | None:
    """If ``code`` matches, return the remaining hashes (code removed); otherwise None."""
    hashed = _hash_code(code)
    remaining = list(stored_hashes or [])
    for candidate in remaining:
        if hmac.compare_digest(candidate, hashed):
            remaining.remove(candidate)
            return remaining
    return None
