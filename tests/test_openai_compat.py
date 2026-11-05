# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from llm_gateway.errors import ProviderRejected, ProviderTimeout, ProviderUnavailable
from llm_gateway.providers import CompletionRequest, OpenAICompatProvider


def make(handler: httpx.MockTransport, key: str | None = "k") -> OpenAICompatProvider:
    return OpenAICompatProvider(
        base_url="http://upstream/v1/", model="m", api_key=key,
        client=httpx.AsyncClient(transport=handler),
    )  # fmt: skip


def run(provider: OpenAICompatProvider, system: str | None = None) -> str:
    return asyncio.run(provider.complete(CompletionRequest("hi", system, 64)))


def ok(content: object = "pong") -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )


def test_success_builds_the_expected_request() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    assert run(make(httpx.MockTransport(handler)), system="be brief") == "pong"
    assert seen["url"] == "http://upstream/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    body = seen["body"]
    assert isinstance(body, dict) and body["max_tokens"] == 64 and body["stream"] is False
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_no_auth_header_without_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    assert run(make(httpx.MockTransport(handler), key=None)) == "x"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_statuses(status: int) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status, text="SECRET-BODY"))
    with pytest.raises(ProviderUnavailable) as info:
        run(make(transport))
    assert "SECRET-BODY" not in str(info.value) and str(status) in str(info.value)


@pytest.mark.parametrize("status", [400, 401, 404])
def test_client_errors_are_rejections(status: int) -> None:
    with pytest.raises(ProviderRejected):
        run(make(httpx.MockTransport(lambda r: httpx.Response(status))))


def test_timeout_and_transport_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderTimeout):
        run(make(httpx.MockTransport(timeout)))
    with pytest.raises(ProviderUnavailable):
        run(make(httpx.MockTransport(refused)))


@pytest.mark.parametrize(
    "transport",
    [
        httpx.MockTransport(lambda r: httpx.Response(200, text="not json")),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": []})),
        ok(content=123),
    ],
)
def test_unusable_responses(transport: httpx.MockTransport) -> None:
    with pytest.raises(ProviderUnavailable):
        run(make(transport))


def test_aclose() -> None:
    asyncio.run(make(ok()).aclose())
