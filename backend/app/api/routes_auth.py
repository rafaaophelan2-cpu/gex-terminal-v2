from fastapi import APIRouter, Cookie, HTTPException, Request, Response

from app.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password_argon2,
    login_rate_limiter,
    verify_password,
)
from app.integrations.supabase_client import fetch_user_by_username, update_user_password_hash
from app.models.schemas import LoginRequest, LoginResponse, MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

COOKIE_NAME = "gex_session"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, response: Response):
    username = payload.username.strip().lower()
    password = payload.password.strip()
    ip = _client_ip(request)

    if not username or not password:
        raise HTTPException(status_code=400, detail="Usuario y contraseña son obligatorios.")

    locked_seconds = login_rate_limiter.check_locked(username, ip)
    if locked_seconds > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Demasiados intentos fallidos. Espera {int(locked_seconds) + 1}s antes de reintentar.",
        )

    user_record = await fetch_user_by_username(username)
    if not user_record:
        login_rate_limiter.register_failure(username, ip)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    stored_hash = str(user_record.get("password_hash", ""))
    is_valid, needs_rehash = verify_password(password, stored_hash)

    if not is_valid:
        login_rate_limiter.register_failure(username, ip)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    login_rate_limiter.register_success(username, ip)

    if needs_rehash:
        # Upgrade perezoso: el hash legado (SHA256) que sí funcionó se
        # reemplaza por argon2, sin pedirle nada al usuario ni invalidar
        # su sesión actual.
        await update_user_password_hash(username, hash_password_argon2(password))

    token = create_access_token(subject=username)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.jwt_access_ttl_minutes * 60,
    )

    display_name = user_record.get("name", username)
    return LoginResponse(ok=True, message=f"Bienvenido {display_name}", username=username)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(gex_session: str | None = Cookie(default=None)):
    if not gex_session:
        raise HTTPException(status_code=401, detail="No autenticado.")
    username = decode_access_token(gex_session)
    if not username:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")
    return MeResponse(username=username)
