from pydantic import BaseModel, field_validator


def _normalize_symbol(value: str) -> str:
    """Mismo motivo que _normalize_symbol en routes_rest.py -- acá cubre
    los dos endpoints que reciben el símbolo en el BODY (AiDiagnosisRequest,
    ChatMessageRequest) en vez de query param, para que 'qqq' no busque un
    feed que solo existe bajo la clave 'QQQ'."""
    return value.strip().upper()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool
    message: str
    username: str | None = None
    token: str | None = None


class MeResponse(BaseModel):
    username: str


class AiDiagnosisRequest(BaseModel):
    symbol: str = "QQQ"
    tipo_analisis: str = "Posibles Escenarios"
    conversion_ratio: float | None = None

    _normalize_symbol = field_validator("symbol")(_normalize_symbol)


class AiDiagnosisResponse(BaseModel):
    text: str
    source: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    messages: list[ChatMessage]


class ChatMessageRequest(BaseModel):
    symbol: str = "QQQ"
    message: str
    conversion_ratio: float | None = None

    _normalize_symbol = field_validator("symbol")(_normalize_symbol)


class ChatMessageResponse(BaseModel):
    role: str = "assistant"
    content: str
    source: str
