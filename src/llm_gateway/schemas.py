from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class ChatMessage(BaseModel):
    """One text turn. Tool messages and tool calls are not supported (extra fields are refused)."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str

    _check = field_validator("content")(_not_blank)


class ChatCompletionRequest(BaseModel):
    """Text-only subset of the OpenAI chat-completions request.

    ``model`` is accepted for client compatibility and ignored: the provider chain decides.
    ``stream`` and ``tools`` are parsed only so that they can be refused with a clear code.
    """

    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    messages: list[ChatMessage] = Field(min_length=1)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False
    tools: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def _needs_a_user_turn(self) -> ChatCompletionRequest:
        if not any(m.role != "system" for m in self.messages):
            raise ValueError("at least one user or assistant message is required")
        return self


class ChatChoiceMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatChoiceMessage
    finish_reason: Literal["stop", "length"]


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    model: str
    choices: list[ChatChoice]
