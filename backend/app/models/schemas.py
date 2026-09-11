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


class AiDiagnosisRequest(BaseModel):
    symbol: str = "QQQ"
    tipo_analisis: str = "Intradía"


class AiDiagnosisResponse(BaseModel):
    text: str
    source: str
