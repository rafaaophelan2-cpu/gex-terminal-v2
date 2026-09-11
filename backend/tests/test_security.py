import hashlib
import time

import pytest
from fastapi import HTTPException

from app.core.security import (
    LoginRateLimiter,
    create_access_token,
    decode_access_token,
    hash_password_argon2,
    require_auth,
    verify_password,
)


def test_verify_password_legacy_sha256_valid():
    password = "correcthorse"
    sha256_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    is_valid, needs_rehash = verify_password(password, sha256_hash)
    assert is_valid is True
    assert needs_rehash is True  # legado SHA256 -> debe migrarse


def test_verify_password_legacy_sha256_invalid():
    sha256_hash = hashlib.sha256(b"correcthorse").hexdigest()
    is_valid, needs_rehash = verify_password("wrongpassword", sha256_hash)
    assert is_valid is False
    assert needs_rehash is False


def test_verify_password_argon2_valid():
    password = "correcthorse"
    argon2_hash = hash_password_argon2(password)
    is_valid, needs_rehash = verify_password(password, argon2_hash)
    assert is_valid is True
    assert needs_rehash is False  # ya está en argon2, no hace falta re-hashear


def test_verify_password_argon2_invalid():
    argon2_hash = hash_password_argon2("correcthorse")
    is_valid, needs_rehash = verify_password("wrongpassword", argon2_hash)
    assert is_valid is False
    assert needs_rehash is False


def test_jwt_roundtrip():
    token = create_access_token(subject="trader1")
    username = decode_access_token(token)
    assert username == "trader1"


def test_jwt_invalid_token_returns_none():
    assert decode_access_token("not-a-real-token") is None


def test_require_auth_accepts_bearer_header():
    token = create_access_token(subject="trader1")
    username = require_auth(gex_session=None, authorization=f"Bearer {token}")
    assert username == "trader1"


def test_require_auth_accepts_bearer_header_case_insensitive_scheme():
    token = create_access_token(subject="trader1")
    username = require_auth(gex_session=None, authorization=f"bearer {token}")
    assert username == "trader1"


def test_require_auth_falls_back_to_cookie_when_no_bearer_header():
    # Compatibilidad con logins previos al cambio a Authorization/localStorage.
    token = create_access_token(subject="trader1")
    username = require_auth(gex_session=token, authorization=None)
    assert username == "trader1"


def test_require_auth_prefers_bearer_over_cookie():
    bearer_token = create_access_token(subject="trader1")
    cookie_token = create_access_token(subject="trader2")
    username = require_auth(gex_session=cookie_token, authorization=f"Bearer {bearer_token}")
    assert username == "trader1"


def test_require_auth_raises_401_without_any_credential():
    with pytest.raises(HTTPException) as exc_info:
        require_auth(gex_session=None, authorization=None)
    assert exc_info.value.status_code == 401


def test_require_auth_raises_401_for_expired_or_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        require_auth(gex_session=None, authorization="Bearer not-a-real-token")
    assert exc_info.value.status_code == 401


def test_rate_limiter_locks_after_max_attempts():
    limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=60)
    assert limiter.check_locked("trader1", "1.2.3.4") == 0.0

    for _ in range(3):
        limiter.register_failure("trader1", "1.2.3.4")

    remaining = limiter.check_locked("trader1", "1.2.3.4")
    assert remaining > 0.0


def test_rate_limiter_success_clears_failures():
    limiter = LoginRateLimiter(max_attempts=3, lockout_seconds=60)
    limiter.register_failure("trader1", "1.2.3.4")
    limiter.register_failure("trader1", "1.2.3.4")
    limiter.register_success("trader1", "1.2.3.4")

    # Un tercer fallo despues de un exito no deberia bloquear (el contador se reinicio)
    limiter.register_failure("trader1", "1.2.3.4")
    assert limiter.check_locked("trader1", "1.2.3.4") == 0.0


def test_rate_limiter_is_scoped_per_username_and_ip():
    limiter = LoginRateLimiter(max_attempts=2, lockout_seconds=60)
    limiter.register_failure("trader1", "1.2.3.4")
    limiter.register_failure("trader1", "1.2.3.4")
    assert limiter.check_locked("trader1", "1.2.3.4") > 0.0
    # Mismo usuario, otra IP -> no deberia estar bloqueado
    assert limiter.check_locked("trader1", "9.9.9.9") == 0.0
    # Otro usuario, misma IP -> tampoco deberia estar bloqueado
    assert limiter.check_locked("trader2", "1.2.3.4") == 0.0
