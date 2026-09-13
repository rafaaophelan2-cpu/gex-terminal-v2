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
