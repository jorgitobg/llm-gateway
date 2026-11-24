"""Opt-in same-provider retry: offline, fake clock and fake sleep, content-free."""

from __future__ import annotations

import asyncio
import logging

import pytest

from llm_gateway.errors import ProviderRejected, ProviderTimeout, ProviderUnavailable
from llm_gateway.providers import ProviderChain, build_chain
from llm_gateway.providers.base import CompletionRequest
from llm_gateway.providers.chain import RetryPolicy
from llm_gateway.settings import Settings

REQ = CompletionRequest(prompt="SECRET-PROMPT-MARKER")


class Scripted:
    """Provider that plays back a script: an exception instance to raise or a str to return."""

    def __init__(self, name: str, *script: BaseException | str) -> None:
        self.name = name
        self._script = list(script)
        self.calls = 0

    async def complete(self, request: CompletionRequest) -> str:
        self.calls += 1
        step = self._script.pop(0) if self._script else "ok-text"
        if isinstance(step, BaseException):
            raise step
        return step


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def chain(
    providers: list[Scripted],
    ft: FakeTime,
    *,
    attempts: int = 3,
    backoff: float = 0.0,
    deadline: float | None = None,
    threshold: int = 2,
) -> ProviderChain:
    return ProviderChain(
        providers,
        timeout_s=1.0,
        breaker_threshold=threshold,
        clock=ft.clock,
        retry=RetryPolicy(attempts, backoff_s=backoff, deadline_s=deadline),
        sleep=ft.sleep,
    )


def run(c: ProviderChain) -> object:
    return asyncio.run(c.run(REQ))


def test_default_policy_is_one_attempt_and_unchanged_behaviour() -> None:
    p = Scripted("a", ProviderUnavailable("x"), "never")
    b = Scripted("b", "from-b")
    c = ProviderChain([p, b], timeout_s=1.0)
    result = asyncio.run(c.run(REQ))
    assert RetryPolicy().max_attempts == 1
    assert (p.calls, b.calls) == (1, 1)
    assert [(a.provider, a.outcome) for a in result.attempts] == [
        ("a", "unavailable"),
        ("b", "ok"),
    ]


def test_transient_failure_recovers_on_same_provider() -> None:
    ft = FakeTime()
    a = Scripted("a", ProviderUnavailable("x"), ProviderTimeout("t"), "fine")
    b = Scripted("b")
    result = asyncio.run(chain([a, b], ft).run(REQ))
    assert result.provider == "a" and result.text == "fine"
    assert a.calls == 3 and b.calls == 0
    assert [x.outcome for x in result.attempts] == ["unavailable", "timeout", "ok"]
    assert {x.provider for x in result.attempts} == {"a"}


def test_exhaustion_fails_over_after_max_attempts() -> None:
    ft = FakeTime()
    a = Scripted("a", *[ProviderUnavailable("x")] * 5)
    b = Scripted("b", "from-b")
    result = asyncio.run(chain([a, b], ft, attempts=3).run(REQ))
    assert a.calls == 3 and result.provider == "b"
    assert [x.outcome for x in result.attempts] == ["unavailable"] * 3 + ["ok"]


def test_permanent_errors_are_never_retried() -> None:
    ft = FakeTime()
    a = Scripted("a", ProviderRejected("no"), "never")
    with pytest.raises(Exception) as info:
        asyncio.run(chain([a, Scripted("b")], ft).run(REQ))
    assert a.calls == 1 and ft.sleeps == []
    assert getattr(info.value, "code", None) == "upstream_rejected"


def test_backoff_sleeps_between_retries_only() -> None:
    ft = FakeTime()
    a = Scripted("a", ProviderUnavailable("x"), ProviderUnavailable("x"), "fine")
    asyncio.run(chain([a], ft, backoff=0.5).run(REQ))
    assert ft.sleeps == [0.5, 0.5]


def test_deadline_stops_retries_before_attempts_run_out() -> None:
    ft = FakeTime()
    a = Scripted("a", *[ProviderUnavailable("x")] * 10)
    b = Scripted("b", "from-b")
    # each retry needs 0.4 s of backoff; a 1.0 s budget allows two retries, not three
    result = asyncio.run(chain([a, b], ft, attempts=10, backoff=0.4, deadline=1.0).run(REQ))
    assert a.calls == 3 and result.provider == "b"
    assert sum(ft.sleeps) <= 1.0


def test_breaker_counts_final_outcome_not_each_retry() -> None:
    ft = FakeTime()
    a = Scripted("a", *[ProviderUnavailable("x")] * 3)
    b = Scripted("b")
    c = chain([a, b], ft, attempts=3, threshold=2)
    asyncio.run(c.run(REQ))  # 3 tries on a = ONE breaker failure (threshold is 2)
    result = asyncio.run(c.run(REQ))  # a still closed: tried again (script exhausted -> ok)
    assert result.provider == "a"
    assert a.calls == 4


def test_breaker_opens_after_threshold_exhausted_runs() -> None:
    ft = FakeTime()
    a = Scripted("a", *[ProviderUnavailable("x")] * 4)
    c = chain([a, Scripted("b")], ft, attempts=2, threshold=2)
    asyncio.run(c.run(REQ))
    asyncio.run(c.run(REQ))
    result = asyncio.run(c.run(REQ))
    assert result.attempts[0].outcome == "circuit_open" and a.calls == 4


def test_retry_attempts_do_not_log_or_store_content(caplog: pytest.LogCaptureFixture) -> None:
    ft = FakeTime()
    a = Scripted("a", ProviderUnavailable("x"), "fine")
    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(chain([a], ft).run(REQ))
    assert "SECRET-PROMPT-MARKER" not in caplog.text
    assert "SECRET-PROMPT-MARKER" not in repr(result.attempts)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"max_attempts": 11},
        {"max_attempts": True},
        {"max_attempts": 2, "backoff_s": -1.0},
        {"max_attempts": 2, "backoff_s": float("inf")},
        {"max_attempts": 2, "deadline_s": 0.0},
        {"max_attempts": 2, "deadline_s": float("nan")},
    ],
)
def test_policy_validation(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="retry"):
        RetryPolicy(**kwargs)  # type: ignore[arg-type]


def test_settings_default_off_and_env_wiring() -> None:
    assert Settings().retry_attempts == 1
    cfg = Settings.from_env(
        {
            "LLM_GATEWAY_RETRY_ATTEMPTS": "3",
            "LLM_GATEWAY_RETRY_BACKOFF_S": "0.25",
            "LLM_GATEWAY_RETRY_DEADLINE_S": "5",
        }
    )
    assert (cfg.retry_attempts, cfg.retry_backoff_s, cfg.retry_deadline_s) == (3, 0.25, 5.0)
    built = build_chain(cfg)
    assert built.retry == RetryPolicy(3, backoff_s=0.25, deadline_s=5.0)
    assert build_chain(Settings()).retry == RetryPolicy()
