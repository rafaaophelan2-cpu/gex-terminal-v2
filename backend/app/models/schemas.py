from pydantic import BaseModel


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
    tipo_analisis: str = "Intradía"
    conversion_ratio: float | None = None


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


class ChatMessageResponse(BaseModel):
    role: str = "assistant"
    content: str
    source: str
