from __future__ import annotations

import asyncio
from typing import Literal

from llm_gateway.errors import ProviderRejected, ProviderUnavailable
from llm_gateway.providers.base import CompletionRequest

Mode = Literal["ok", "hang", "unavailable", "rejected"]


class FakeProvider:
    """Deterministic offline provider with simulated failure modes. Keeps no request content."""

    def __init__(self, name: str = "fake", mode: Mode = "ok") -> None:
        self.name = name
        self.mode: Mode = mode
        self.calls = 0

    async def complete(self, request: CompletionRequest) -> str:
        self.calls += 1
        if self.mode == "hang":
            await asyncio.sleep(3600)
        if self.mode == "unavailable":
            raise ProviderUnavailable("simulated outage")
        if self.mode == "rejected":
            raise ProviderRejected("simulated rejection")
        return f"[{self.name}] completion for a {len(request.prompt)}-character prompt"
