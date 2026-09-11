import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Header, HTTPException
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()
_argon2 = PasswordHasher()


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Verifica una contraseña contra el hash guardado en Supabase.

    Soporta dos formatos en la columna password_hash, igual que login_user
    en app.py (~línea 432): el legado SHA256 hex (comparado con
    hmac.compare_digest para evitar timing attacks) y argon2 (prefijo
    "$argon2"). Devuelve (es_valida, necesita_rehash) — necesita_rehash es
    True cuando el hash es el SHA256 legado y debe migrarse a argon2 de
    forma perezosa tras un login exitoso, sin exigirle nada al usuario.
    """
    stored_hash = (stored_hash or "").strip()

    if stored_hash.startswith("$argon2"):
        try:
            _argon2.verify(stored_hash, password)
            return True, False
        except VerifyMismatchError:
            return False, False
        except Exception:
            return False, False

    sha256_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    is_valid = hmac.compare_digest(stored_hash, sha256_hash)
    return is_valid, is_valid


def hash_password_argon2(password: str) -> str:
    return _argon2.hash(password)


def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_access_ttl_minutes)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": expires}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """Devuelve el 'sub' (username) del token si es válido, o None si
    expiró / es inválido / fue firmado con otra clave."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None


def require_auth(
    gex_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    """Dependency de FastAPI para proteger endpoints REST: acepta el token
    por header 'Authorization: Bearer <token>' (lo que manda el frontend
    ahora, guardado en localStorage) o, como respaldo, por la cookie
    'gex_session' de logins previos. El cookie cross-site (backend en
    onrender.com, frontend en pages.dev -- dominios distintos) resultó
    poco confiable en la práctica: navegadores con bloqueo de cookies de
    terceros activado por defecto (Safari con "Prevent Cross-Site
    Tracking", Firefox en modo estricto, etc.) simplemente descartan esa
    cookie sin avisar -- el login parecía funcionar (200 OK) pero la
    siguiente llamada a la API llegaba sin cookie y caía acá con 401,
    devolviendo al usuario al login con un mensaje confuso de "sesión
    expirada" segundos después de haber iniciado sesión bien. El header
    Authorization no depende de cookies en absoluto, así que no tiene
    ese problema en ningún navegador/configuración."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    elif gex_session:
        token = gex_session

    if not token:
        raise HTTPException(status_code=401, detail="No autenticado.")
    username = decode_access_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")
    return username


class LoginRateLimiter:
    """Rate limiting de intentos de login por (username, ip) en memoria del
    proceso. A diferencia del original en app.py (que usaba st.session_state,
    o sea por SESIÓN de navegador), esto sí protege a nivel de servidor:
    5 intentos fallidos -> bloqueo de 60s para esa combinación."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 60):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def _key(self, username: str, ip: str) -> str:
        return f"{username.strip().lower()}::{ip}"

    def check_locked(self, username: str, ip: str) -> float:
        """Devuelve segundos restantes de bloqueo (0 si no está bloqueado)."""
        key = self._key(username, ip)
        locked_until = self._locked_until.get(key, 0.0)
        remaining = locked_until - time.time()
        return max(remaining, 0.0)

    def register_failure(self, username: str, ip: str) -> None:
        key = self._key(username, ip)
        self._failures[key] = self._failures.get(key, 0) + 1
        if self._failures[key] >= self.max_attempts:
            self._locked_until[key] = time.time() + self.lockout_seconds
            self._failures[key] = 0

    def register_success(self, username: str, ip: str) -> None:
        key = self._key(username, ip)
        self._failures.pop(key, None)
        self._locked_until.pop(key, None)


login_rate_limiter = LoginRateLimiter()
