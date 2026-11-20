# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from tests.conftest import MakeClient

MARKER = "ZX-CHAT-MARKER-7731"


def _body(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": "anything",
        "messages": [{"role": "user", "content": "hello"}],
    }
    base.update(extra)
    return base


def test_returns_an_openai_shaped_completion(make_client: MakeClient) -> None:
    client, providers = make_client("ok")
    response = client.post("/v1/chat/completions", json=_body(max_tokens=64))
    data = response.json()
    assert response.status_code == 200
    assert data["object"] == "chat.completion"
    choice = data["choices"][0]
    assert choice["index"] == 0 and choice["finish_reason"] == "stop"
    assert choice["message"] == {
        "role": "assistant",
        "content": "[p0] completion for a 5-character prompt",
    }
    assert "usage" not in data  # the gateway does not count tokens
    assert providers[0].calls == 1


def test_system_messages_become_system_and_turns_become_a_transcript(
    make_client: MakeClient,
) -> None:
    from llm_gateway.app import flatten_messages
    from llm_gateway.schemas import ChatMessage

    system, prompt = flatten_messages(
        [
            ChatMessage(role="system", content="be brief"),
            ChatMessage(role="user", content="one"),
            ChatMessage(role="assistant", content="two"),
            ChatMessage(role="user", content="three"),
        ]
    )
    assert system == "be brief"
    assert prompt == "user: one\nassistant: two\nuser: three"
    only = flatten_messages([ChatMessage(role="user", content="solo")])
    assert only == (None, "solo")


def test_fallback_is_reported_in_the_provider_field(make_client: MakeClient) -> None:
    client, providers = make_client("unavailable", "ok")
    data = client.post("/v1/chat/completions", json=_body()).json()
    assert data["model"] == "p1"
    assert [p.calls for p in providers] == [1, 1]


def test_max_tokens_is_capped_and_never_raised(make_client: MakeClient) -> None:
    client, _ = make_client("ok")
    ok = client.post("/v1/chat/completions", json=_body(max_tokens=10_000_000))
    assert ok.status_code == 200  # capped to the configured limit, not rejected
    assert client.post("/v1/chat/completions", json=_body(max_tokens=0)).status_code == 422


@pytest.mark.parametrize(
    "extra",
    [
        {"stream": True},
        {"tools": [{"type": "function", "function": {"name": "x"}}]},
    ],
)
def test_streaming_and_tools_are_refused_before_any_provider_call(
    make_client: MakeClient, extra: dict[str, Any]
) -> None:
    client, providers = make_client("ok")
    response = client.post("/v1/chat/completions", json=_body(**extra))
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"streaming_not_supported", "tools_not_supported"}
    assert providers[0].calls == 0


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": "   "}],
        [{"role": "user", "content": "a", "tool_calls": []}],
        [{"role": "system", "content": "only system"}],
    ],
)
def test_invalid_message_lists_are_422(make_client: MakeClient, messages: list[Any]) -> None:
    client, providers = make_client("ok")
    response = client.post("/v1/chat/completions", json=_body(messages=messages))
    assert response.status_code == 422
    assert providers[0].calls == 0


def test_oversized_transcript_is_413(make_client: MakeClient) -> None:
    client, providers = make_client("ok", max_prompt_chars=50)
    response = client.post(
        "/v1/chat/completions",
        json=_body(messages=[{"role": "user", "content": "x" * 60}]),
    )
    assert response.status_code == 413
    assert providers[0].calls == 0


def test_all_providers_down_is_503(make_client: MakeClient) -> None:
    client, _ = make_client("unavailable")
    response = client.post("/v1/chat/completions", json=_body())
    assert response.status_code == 503


def test_logs_never_contain_message_content(
    make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = make_client("unavailable", "ok")
    logger = logging.getLogger("llm_gateway.access")
    logger.propagate = True
    with caplog.at_level(logging.INFO, logger="llm_gateway.access"):
        client.post(
            "/v1/chat/completions",
            json=_body(
                messages=[
                    {"role": "system", "content": MARKER},
                    {"role": "user", "content": MARKER},
                ]
            ),
        )
    logger.propagate = False
    text = json.dumps([r.__dict__ for r in caplog.records], default=str)
    assert caplog.records and MARKER not in text
