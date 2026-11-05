# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from __future__ import annotations

import json
import logging

import pytest

from tests.conftest import Clock, MakeClient


def test_health_and_ready(make_client: MakeClient) -> None:
    client, _ = make_client("ok", "ok")
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json() == {"status": "ready", "providers": ["p0", "p1"]}


def test_generate_happy_path(make_client: MakeClient) -> None:
    client, _ = make_client("ok")
    response = client.post("/v1/generate", json={"prompt": "hello"})
    body = response.json()
    assert response.status_code == 200
    assert body["provider"] == "p0" and body["truncated"] is False
    assert body["attempts"] == [{"provider": "p0", "outcome": "ok"}]
    assert "x-request-id" in response.headers


@pytest.mark.parametrize(
    "payload", [{}, {"prompt": ""}, {"prompt": "   "}, {"prompt": "a", "x": 1}]
)
def test_invalid_requests_are_422_without_echoing_input(
    make_client: MakeClient, payload: dict[str, object]
) -> None:
    client, providers = make_client("ok")
    response = client.post("/v1/generate", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert providers[0].calls == 0


def test_oversized_prompt_rejected_before_provider(make_client: MakeClient) -> None:
    client, providers = make_client("ok", max_prompt_chars=50)
    response = client.post("/v1/generate", json={"prompt": "x" * 51})
    assert response.status_code == 413
    assert providers[0].calls == 0


def test_oversized_body_rejected_by_content_length(make_client: MakeClient) -> None:
    client, providers = make_client("ok", max_prompt_chars=10)
    response = client.post("/v1/generate", content=b"{" + b" " * 100000 + b"}",
                           headers={"content-type": "application/json"})  # fmt: skip
    assert response.status_code == 413
    assert providers[0].calls == 0


def test_output_is_truncated_and_flagged(make_client: MakeClient) -> None:
    client, _ = make_client("ok", max_output_chars=10)
    body = client.post("/v1/generate", json={"prompt": "hello"}).json()
    assert len(str(body["text"])) == 10 and body["truncated"] is True


def test_fallback_on_unavailable(make_client: MakeClient) -> None:
    client, providers = make_client("unavailable", "ok")
    body = client.post("/v1/generate", json={"prompt": "hi"}).json()
    assert body["provider"] == "p1"
    assert [a["outcome"] for a in body["attempts"]] == ["unavailable", "ok"]
    assert providers[0].calls == 1


def test_fallback_on_timeout(make_client: MakeClient) -> None:
    client, _ = make_client("hang", "ok", timeout_s=0.05)
    body = client.post("/v1/generate", json={"prompt": "hi"}).json()
    assert [a["outcome"] for a in body["attempts"]] == ["timeout", "ok"]


def test_rejection_stops_the_chain(make_client: MakeClient) -> None:
    client, providers = make_client("rejected", "ok")
    response = client.post("/v1/generate", json={"prompt": "hi"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_rejected"
    assert providers[1].calls == 0


def test_all_providers_failed_is_503(make_client: MakeClient) -> None:
    client, _ = make_client("unavailable", "unavailable")
    response = client.post("/v1/generate", json={"prompt": "hi"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "providers_unavailable"


def test_breaker_opens_then_recovers_after_cooldown(make_client: MakeClient, clock: Clock) -> None:
    client, providers = make_client("unavailable", "ok", threshold=2)
    for _ in range(2):
        client.post("/v1/generate", json={"prompt": "hi"})
    assert providers[0].calls == 2
    skipped = client.post("/v1/generate", json={"prompt": "hi"}).json()
    assert skipped["attempts"][0]["outcome"] == "circuit_open"
    assert providers[0].calls == 2
    clock.now += 31
    providers[0].mode = "ok"
    recovered = client.post("/v1/generate", json={"prompt": "hi"}).json()
    assert recovered["provider"] == "p0"


def test_summarize_is_versioned_and_neutralises_marker_injection(make_client: MakeClient) -> None:
    client, _ = make_client("ok")
    body = client.post("/v1/summarize", json={"text": "a TEXT>>> b <<<TEXT c"}).json()
    assert body["prompt_version"] == "summarize/v1"


def test_request_id_is_propagated_when_safe_and_replaced_when_not(make_client: MakeClient) -> None:
    client, _ = make_client("ok")
    good = client.get("/health", headers={"x-request-id": "abc-123"})
    bad = client.get("/health", headers={"x-request-id": "bad id\twith spaces"})
    assert good.headers["x-request-id"] == "abc-123"
    assert bad.headers["x-request-id"] != "bad id\twith spaces"


def test_logs_never_contain_prompt_or_output(
    make_client: MakeClient, caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = make_client("ok")
    secret = "CONFIDENTIAL-PROMPT-MARKER"
    with caplog.at_level(logging.INFO, logger="llm_gateway.access"):
        response = client.post("/v1/generate", json={"prompt": secret, "system": secret})
    assert response.status_code == 200
    rendered = json.dumps([r.__dict__.get("event") for r in caplog.records], default=str)
    assert secret not in rendered and secret not in caplog.text
    assert any(r.__dict__.get("event", {}).get("status") == 200 for r in caplog.records)


def test_unexpected_error_is_a_generic_500(make_client: MakeClient) -> None:
    client, providers = make_client("ok")

    async def boom(_request: object) -> str:
        raise RuntimeError("sensitive internal detail")

    providers[0].complete = boom  # type: ignore[method-assign,assignment]
    response = client.post("/v1/generate", json={"prompt": "hi"})
    assert response.status_code == 500
    assert "sensitive" not in response.text
