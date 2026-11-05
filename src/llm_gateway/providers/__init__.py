from __future__ import annotations

from llm_gateway.providers.base import CompletionRequest, Provider
from llm_gateway.providers.chain import AllProvidersFailed, Attempt, ChainResult, ProviderChain
from llm_gateway.providers.fake import FakeProvider
from llm_gateway.providers.openai_compat import OpenAICompatProvider
from llm_gateway.settings import Settings

__all__ = [
    "AllProvidersFailed",
    "Attempt",
    "ChainResult",
    "CompletionRequest",
    "FakeProvider",
    "OpenAICompatProvider",
    "Provider",
    "ProviderChain",
    "build_chain",
]


def build_chain(settings: Settings) -> ProviderChain:
    providers: list[Provider] = []
    for name in settings.providers:
        if name == "fake":
            providers.append(FakeProvider())
        else:
            providers.append(
                OpenAICompatProvider(
                    base_url=settings.upstream_base_url,
                    model=settings.upstream_model,
                    api_key=settings.upstream_api_key,
                )
            )
    return ProviderChain(
        providers,
        timeout_s=settings.provider_timeout_s,
        breaker_threshold=settings.breaker_threshold,
        breaker_cooldown_s=settings.breaker_cooldown_s,
    )
