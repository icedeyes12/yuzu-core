from __future__ import annotations

from app.core.llm_context import LLMContext
from app.providers.chutes import ChutesProvider
from app.providers.google import GoogleProvider
from app.providers.openrouter import OpenRouterProvider


def test_openrouter_uses_stable_chat_session_id() -> None:
    ctx = LLMContext(
        provider="openrouter",
        model="openai/gpt-4o-mini",
        api_key="test-key",
        chat_session_id="chat-session-1",
    )

    _, payload = OpenRouterProvider()._prepare_payload(
        ctx, [{"role": "user", "content": "hello"}], False
    )

    assert payload["session_id"] == "chat-session-1"


def test_non_openrouter_providers_do_not_receive_openrouter_session_field() -> None:
    google_ctx = LLMContext(
        provider="google",
        model="gemini-2.5-flash",
        api_key="test-key",
        chat_session_id="s1",
    )
    _, google_payload = GoogleProvider()._prepare_payload(
        google_ctx, [{"role": "user", "content": "hello"}], False
    )

    chutes_ctx = LLMContext(
        provider="chutes", model="model", api_key="test-key", chat_session_id="s1"
    )
    _, chutes_payload = ChutesProvider()._prepare_payload(
        chutes_ctx, "model", [{"role": "user", "content": "hello"}], False
    )

    assert "session_id" not in google_payload
    assert "session_id" not in chutes_payload


def test_openrouter_session_id_is_unchanged_for_streaming_payload() -> None:
    ctx = LLMContext(
        provider="openrouter",
        model="openai/gpt-4o-mini",
        api_key="test-key",
        chat_session_id="chat-session-1",
    )

    _, payload = OpenRouterProvider()._prepare_payload(
        ctx, [{"role": "user", "content": "hello"}], True
    )

    assert payload["session_id"] == "chat-session-1"


def test_different_contexts_keep_distinct_session_ids() -> None:
    provider = OpenRouterProvider()
    payloads = [
        provider._prepare_payload(
            LLMContext(
                provider="openrouter",
                model="model",
                api_key="test-key",
                chat_session_id=session_id,
            ),
            [{"role": "user", "content": "hello"}],
            False,
        )[1]
        for session_id in ("session-a", "session-b")
    ]

    assert [payload["session_id"] for payload in payloads] == ["session-a", "session-b"]


__all__ = []


if __name__ == "__main__":
    test_openrouter_uses_stable_chat_session_id()
    test_non_openrouter_providers_do_not_receive_openrouter_session_field()
    test_openrouter_session_id_is_unchanged_for_streaming_payload()
    test_different_contexts_keep_distinct_session_ids()
    print("ok")
