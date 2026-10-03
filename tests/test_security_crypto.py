from app.utils.crypto import encrypt_token, decrypt_token
from app.routers.auth import hash_password, verify_password, create_access_token
from jose import jwt
from app.config import settings


def test_token_encryption_and_decryption():
    raw_token = "ya29.a0AfH6SMD_Sample_Secret_OAuth_Token_12345"
    encrypted = encrypt_token(raw_token)
    assert encrypted != raw_token
    assert len(encrypted) > 20

    decrypted = decrypt_token(encrypted)
    assert decrypted == raw_token


def test_token_decryption_legacy_fallback():
    # If legacy plain text token is passed, it returns the raw token gracefully
    plain_token = "legacy-plaintext-token"
    result = decrypt_token(plain_token)
    assert result == plain_token


def test_password_hashing_and_verification():
    password = "SecurePassword123!"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_creation_and_payload():
    user_data = {"sub": "42", "role": "admin"}
    token = create_access_token(user_data)
    assert token is not None

    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert decoded["sub"] == "42"
    assert decoded["role"] == "admin"
    assert decoded["type"] == "access"
    assert "exp" in decoded
