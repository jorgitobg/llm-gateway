from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CompletionRequest:
    prompt: str
    system: str | None = None
    max_tokens: int = 512


class Provider(Protocol):
    """Provider port. Implementations raise ProviderError subclasses with content-free messages."""

    name: str

    async def complete(self, request: CompletionRequest) -> str: ...
