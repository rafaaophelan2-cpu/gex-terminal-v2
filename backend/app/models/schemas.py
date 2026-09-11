from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool
    message: str
    username: str | None = None


class MeResponse(BaseModel):
    username: str
