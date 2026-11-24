from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from llm_gateway.errors import GatewayError, ProviderError, ProviderTimeout
from llm_gateway.providers.base import CompletionRequest, Provider


@dataclass(frozen=True, slots=True)
class Attempt:
    provider: str
    outcome: str  # ok | timeout | unavailable | rejected | circuit_open


@dataclass(frozen=True, slots=True)
class ChainResult:
    text: str
    provider: str
    attempts: tuple[Attempt, ...]


MAX_RETRY_ATTEMPTS = 10


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Opt-in retry of the *same* provider for transient failures before failing over.

    ``max_attempts`` counts tries per provider per request (1 = no retry, the default).
    ``backoff_s`` is a fixed pause between tries. ``deadline_s`` bounds the total time spent on
    one provider for one request: no retry starts unless time remains after its pause, and every
    try's timeout is capped to what is left of the budget (the first try gets all of it).
    """

    max_attempts: int = 1
    backoff_s: float = 0.0
    deadline_s: float | None = None

    def __post_init__(self) -> None:
        attempts: object = self.max_attempts
        if (
            isinstance(attempts, bool)
            or not isinstance(attempts, int)  # pyright: ignore[reportUnnecessaryIsInstance]
            or not 1 <= attempts <= MAX_RETRY_ATTEMPTS
        ):
            raise ValueError(f"retry max_attempts must be an int in [1, {MAX_RETRY_ATTEMPTS}]")
        if not math.isfinite(self.backoff_s) or self.backoff_s < 0:
            raise ValueError("retry backoff_s must be finite and >= 0")
        if self.deadline_s is not None and (
            not math.isfinite(self.deadline_s) or self.deadline_s <= 0
        ):
            raise ValueError("retry deadline_s must be finite and > 0")


class ProviderChain:
    """Try providers in order with a per-call timeout and a per-provider circuit breaker.

    Retryable failures (timeout, 5xx, 429, bad response) move on to the next provider.
    A rejection (4xx) stops the chain: another provider would get the same bad request.

    With a ``RetryPolicy`` of more than one attempt, a transient failure (timeout or retryable
    error) is first retried on the same provider, within the policy's attempt and deadline
    bounds; every try is recorded as its own ``Attempt``. The breaker counts the final outcome
    of a provider for a request (one failure after retries are exhausted, one success reset),
    not each individual try. Rejections are never retried.
    """

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        timeout_s: float,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = tuple(providers)
        self._timeout_s = timeout_s
        self._threshold = breaker_threshold
        self._cooldown_s = breaker_cooldown_s
        self._clock = clock
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._failures = {p.name: 0 for p in providers}
        self._open_until = {p.name: 0.0 for p in providers}

    @property
    def retry(self) -> RetryPolicy:
        return self._retry

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self._providers)

    def _record_failure(self, name: str) -> None:
        self._failures[name] += 1
        if self._failures[name] >= self._threshold:
            self._open_until[name] = self._clock() + self._cooldown_s
            self._failures[name] = 0

    def _may_retry(self, started: float, policy: RetryPolicy) -> bool:
        if policy.deadline_s is None:
            return True
        return self._clock() + policy.backoff_s < started + policy.deadline_s

    async def run(self, request: CompletionRequest) -> ChainResult:
        attempts: list[Attempt] = []
        for provider in self._providers:
            name = provider.name
            if self._open_until[name] > self._clock():
                attempts.append(Attempt(name, "circuit_open"))
                continue
            policy = self._retry
            started = self._clock()
            for attempt_no in range(1, policy.max_attempts + 1):
                timeout_s = self._timeout_s
                if policy.deadline_s is not None:
                    timeout_s = min(timeout_s, started + policy.deadline_s - self._clock())
                try:
                    async with asyncio.timeout(timeout_s):
                        text = await provider.complete(request)
                except (TimeoutError, ProviderTimeout):
                    outcome = "timeout"
                except ProviderError as error:
                    if not error.retryable:
                        attempts.append(Attempt(name, "rejected"))
                        raise _RejectedError(tuple(attempts)) from error
                    outcome = "unavailable"
                else:
                    self._failures[name] = 0
                    attempts.append(Attempt(name, "ok"))
                    return ChainResult(text, name, tuple(attempts))
                attempts.append(Attempt(name, outcome))
                if attempt_no == policy.max_attempts or not self._may_retry(started, policy):
                    break
                if policy.backoff_s > 0:
                    await self._sleep(policy.backoff_s)
            self._record_failure(name)
        raise AllProvidersFailed(tuple(attempts))

    async def aclose(self) -> None:
        for provider in self._providers:
            closer = getattr(provider, "aclose", None)
            if closer is not None:
                await closer()


class AllProvidersFailed(GatewayError):
    def __init__(self, attempts: tuple[Attempt, ...]) -> None:
        super().__init__(503, "providers_unavailable", "No provider could answer the request")
        self.attempts = attempts


class _RejectedError(GatewayError):
    def __init__(self, attempts: tuple[Attempt, ...]) -> None:
        super().__init__(502, "upstream_rejected", "The upstream provider rejected the request")
        self.attempts = attempts
