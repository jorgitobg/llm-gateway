from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
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


class ProviderChain:
    """Try providers in order with a per-call timeout and a per-provider circuit breaker.

    Retryable failures (timeout, 5xx, 429, bad response) move on to the next provider.
    A rejection (4xx) stops the chain: another provider would get the same bad request.
    """

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        timeout_s: float,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self._providers = tuple(providers)
        self._timeout_s = timeout_s
        self._threshold = breaker_threshold
        self._cooldown_s = breaker_cooldown_s
        self._clock = clock
        self._failures = {p.name: 0 for p in providers}
        self._open_until = {p.name: 0.0 for p in providers}

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self._providers)

    def _record_failure(self, name: str) -> None:
        self._failures[name] += 1
        if self._failures[name] >= self._threshold:
            self._open_until[name] = self._clock() + self._cooldown_s
            self._failures[name] = 0

    async def run(self, request: CompletionRequest) -> ChainResult:
        attempts: list[Attempt] = []
        for provider in self._providers:
            name = provider.name
            if self._open_until[name] > self._clock():
                attempts.append(Attempt(name, "circuit_open"))
                continue
            try:
                async with asyncio.timeout(self._timeout_s):
                    text = await provider.complete(request)
            except TimeoutError:
                attempts.append(Attempt(name, "timeout"))
                self._record_failure(name)
                continue
            except ProviderTimeout:
                attempts.append(Attempt(name, "timeout"))
                self._record_failure(name)
                continue
            except ProviderError as error:
                if not error.retryable:
                    attempts.append(Attempt(name, "rejected"))
                    raise _RejectedError(tuple(attempts)) from error
                attempts.append(Attempt(name, "unavailable"))
                self._record_failure(name)
                continue
            self._failures[name] = 0
            attempts.append(Attempt(name, "ok"))
            return ChainResult(text, name, tuple(attempts))
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
