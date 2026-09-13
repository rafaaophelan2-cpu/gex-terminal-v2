import asyncio
from types import SimpleNamespace

import app.integrations.groq_client as groq_client


class _FakeCompletions:
    def __init__(self, captured):
        self._captured = captured

    def create(self, model, messages, temperature, max_tokens=None):
        self._captured["messages"] = messages
        self._captured["max_tokens"] = max_tokens
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="respuesta de prueba"))])


class _FakeGroq:
    def __init__(self, api_key):
        self.chat = SimpleNamespace(completions=_FakeCompletions(_LAST_CAPTURED))


_LAST_CAPTURED: dict = {}


def test_query_groq_without_history_sends_system_and_user_only(monkeypatch):
    _LAST_CAPTURED.clear()
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr("groq.Groq", _FakeGroq)

    result = asyncio.run(groq_client.query_groq("system prompt", "hola"))

    assert result == "respuesta de prueba"
    assert _LAST_CAPTURED["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hola"},
    ]


def test_query_groq_with_history_includes_prior_turns_in_order(monkeypatch):
    _LAST_CAPTURED.clear()
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr("groq.Groq", _FakeGroq)

    history = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, en qué te ayudo?"},
    ]
    result = asyncio.run(groq_client.query_groq("system prompt", "y el gamma?", history=history))

    assert result == "respuesta de prueba"
    assert _LAST_CAPTURED["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola, en qué te ayudo?"},
        {"role": "user", "content": "y el gamma?"},
    ]


def test_query_groq_sends_generous_max_tokens_to_avoid_truncated_tables(monkeypatch):
    # Regresión: sin max_tokens explícito, el informe completo (5
    # secciones + tabla final) salía cortado en producción -- la tabla
    # del punto 5 quedaba con 1 de 3 filas.
    _LAST_CAPTURED.clear()
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr("groq.Groq", _FakeGroq)

    asyncio.run(groq_client.query_groq("system prompt", "hola"))

    assert _LAST_CAPTURED["max_tokens"] is not None
    assert _LAST_CAPTURED["max_tokens"] >= 2048


def test_query_groq_returns_none_without_api_key(monkeypatch):
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "")
    result = asyncio.run(groq_client.query_groq("system prompt", "hola"))
    assert result is None


def test_query_groq_max_tokens_shrinks_for_a_large_prompt(monkeypatch):
    # Regresión real (confirmada en logs de Render): con max_tokens FIJO,
    # un prompt grande (framework completo + calendario económico de la
    # semana) hacía que prompt+max_tokens superara el límite de TPM de la
    # cuenta en CADA pedido (413 "tokens per minute"), sin llegar nunca a
    # generar nada. Con un prompt grande, max_tokens debe ACHICARSE para
    # dejar presupuesto real dentro del límite.
    _LAST_CAPTURED.clear()
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "fake-key")
    monkeypatch.setattr("groq.Groq", _FakeGroq)

    big_system_prompt = "x" * 20000  # ~6060 tokens estimados
    asyncio.run(groq_client.query_groq(big_system_prompt, "hola"))

    assert _LAST_CAPTURED["max_tokens"] < groq_client.MAX_MAX_TOKENS
    assert _LAST_CAPTURED["max_tokens"] >= groq_client.MIN_MAX_TOKENS


def test_query_groq_skips_the_call_entirely_when_prompt_leaves_no_budget(monkeypatch):
    # Si el prompt SOLO ya deja menos que MIN_MAX_TOKENS de presupuesto,
    # ni vale la pena intentar la llamada -- Groq la va a rechazar con
    # 413 igual, y eso gastaría la ventana de rate limit del minuto sin
    # ninguna chance real de éxito.
    _LAST_CAPTURED.clear()
    monkeypatch.setattr(groq_client.settings, "groq_api_key", "fake-key")
    calls = {"count": 0}

    class _CountingGroq(_FakeGroq):
        def __init__(self, api_key):
            calls["count"] += 1
            super().__init__(api_key)

    monkeypatch.setattr("groq.Groq", _CountingGroq)

    huge_system_prompt = "x" * 30000  # deja menos que MIN_MAX_TOKENS de presupuesto
    result = asyncio.run(groq_client.query_groq(huge_system_prompt, "hola"))

    assert result is None
    assert calls["count"] == 0  # nunca llegó a instanciar el cliente de Groq


def test_estimate_max_tokens_caps_at_the_configured_maximum():
    assert groq_client._estimate_max_tokens(10) == groq_client.MAX_MAX_TOKENS


def test_estimate_max_tokens_returns_none_when_prompt_leaves_no_room():
    huge_prompt_chars = 30000
    assert groq_client._estimate_max_tokens(huge_prompt_chars) is None
