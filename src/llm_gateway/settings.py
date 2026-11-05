from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

KNOWN_PROVIDERS = ("fake", "openai-compatible")


@dataclass(frozen=True, slots=True)
class Settings:
    providers: tuple[str, ...] = ("fake",)
    max_prompt_chars: int = 8000
    max_output_chars: int = 4000
    max_output_tokens: int = 512
    provider_timeout_s: float = 10.0
    breaker_threshold: int = 3
    breaker_cooldown_s: float = 30.0
    upstream_base_url: str = ""
    upstream_model: str = ""
    upstream_api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.providers:
            raise ValueError("at least one provider is required")
        for name in self.providers:
            if name not in KNOWN_PROVIDERS:
                raise ValueError(f"unknown provider: {name}")
        if self.max_prompt_chars < 1 or self.max_output_chars < 1 or self.max_output_tokens < 1:
            raise ValueError("limits must be positive")
        if self.provider_timeout_s <= 0 or self.breaker_cooldown_s < 0:
            raise ValueError("timeouts must be positive")
        if self.breaker_threshold < 1:
            raise ValueError("breaker_threshold must be at least 1")
        if "openai-compatible" in self.providers and not (
            self.upstream_base_url and self.upstream_model
        ):
            raise ValueError("openai-compatible requires upstream base URL and model")

    @property
    def max_body_bytes(self) -> int:
        """Largest accepted Content-Length: 4 UTF-8 bytes per character plus JSON overhead."""
        return self.max_prompt_chars * 4 + 4096

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        def num(key: str, default: float) -> float:
            raw = env.get(key)
            return default if raw is None else float(raw)

        raw_providers = env.get("LLM_GATEWAY_PROVIDERS", "fake")
        providers = tuple(p.strip() for p in raw_providers.split(",") if p.strip())
        return cls(
            providers=providers,
            max_prompt_chars=int(num("LLM_GATEWAY_MAX_PROMPT_CHARS", 8000)),
            max_output_chars=int(num("LLM_GATEWAY_MAX_OUTPUT_CHARS", 4000)),
            max_output_tokens=int(num("LLM_GATEWAY_MAX_OUTPUT_TOKENS", 512)),
            provider_timeout_s=num("LLM_GATEWAY_PROVIDER_TIMEOUT_S", 10.0),
            breaker_threshold=int(num("LLM_GATEWAY_BREAKER_THRESHOLD", 3)),
            breaker_cooldown_s=num("LLM_GATEWAY_BREAKER_COOLDOWN_S", 30.0),
            upstream_base_url=env.get("LLM_GATEWAY_UPSTREAM_BASE_URL", ""),
            upstream_model=env.get("LLM_GATEWAY_UPSTREAM_MODEL", ""),
            upstream_api_key=env.get("LLM_GATEWAY_UPSTREAM_API_KEY") or None,
        )
