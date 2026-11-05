from __future__ import annotations

from typing import Any, Protocol

import pytest
from fastapi.testclient import TestClient

from llm_gateway.app import create_app
from llm_gateway.providers import FakeProvider, ProviderChain
from llm_gateway.settings import Settings


class MakeClient(Protocol):
    def __call__(
        self, *modes: str, timeout_s: float = ..., threshold: int = ..., **settings: Any
    ) -> tuple[TestClient, list[FakeProvider]]: ...


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def make_client(clock: Clock) -> MakeClient:
    def _make(
        *modes: str, timeout_s: float = 0.2, threshold: int = 2, **settings: Any
    ) -> tuple[TestClient, list[FakeProvider]]:
        providers = [
            FakeProvider(f"p{i}", mode=m)  # type: ignore[arg-type]
            for i, m in enumerate(modes or ("ok",))
        ]
        chain = ProviderChain(
            providers, timeout_s=timeout_s, breaker_threshold=threshold,
            breaker_cooldown_s=30.0, clock=clock,
        )  # fmt: skip
        cfg = Settings(**settings)  # type: ignore[arg-type]
        return TestClient(create_app(chain=chain, settings=cfg)), providers

    return _make
