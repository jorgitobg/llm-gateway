from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1)
    system: str | None = None

    _check = field_validator("prompt")(_not_blank)


class SummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)

    _check = field_validator("text")(_not_blank)


class AttemptOut(BaseModel):
    provider: str
    outcome: str


class CompletionResponse(BaseModel):
    text: str
    provider: str
    truncated: bool
    prompt_version: str | None = None
    attempts: list[AttemptOut]
