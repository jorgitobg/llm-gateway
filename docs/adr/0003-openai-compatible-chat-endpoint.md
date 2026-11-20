# ADR 0003: A text-only `/v1/chat/completions` endpoint

Status: accepted (2026-11-20)

## Context

Clients such as [agent-harness](https://github.com/jorgitobg/agent-harness) already speak the OpenAI
chat-completions dialect. The gateway only offered `/v1/generate` (`{prompt, system}`), so putting it in
front of such a client meant writing a bespoke adapter on the client side.

## Decision

Add `POST /v1/chat/completions`, a deliberately small subset:

- accepts `messages` (roles `system`, `user`, `assistant`, text only), optional `max_tokens`, and
  `model` (accepted for compatibility, ignored: the provider chain decides). The response `model` field
  names the provider that actually answered, so a fallback is visible to the caller.
- system messages are joined into `system`; a single user turn is forwarded verbatim; longer transcripts are
  flattened to `role: text` lines.
- `max_tokens` can lower, never raise, the configured output cap.
- it reuses the existing pipeline unchanged: size limits, provider chain, circuit breaker and
  content-free logging (a test asserts a marker string appears in no log record).

## Refused on purpose

- `stream: true` -> `422 streaming_not_supported`; `tools` -> `422 tools_not_supported`; `tool` role and
  `tool_calls` fields fail schema validation. Nothing reaches a provider.
- No `usage` block: the gateway does not count tokens, and inventing numbers would be worse than none.

## Trade-offs

- A harness run through the gateway is single-shot text. Tool use needs a native-tool-calling provider
  path, which means per-provider translation and a bigger failure surface; not attempted here.
- Flattening a multi-turn transcript loses provider-native roles. Acceptable for a gateway whose providers
  share one `prompt` string; wrong for chat-tuned models that depend on role tokens.
- Client-side token budgets in the harness see zero usage, so token and cost budgets cannot trip. Step and
  time budgets still apply.
- The breaker is still per process (ADR 0001): the demo shows one process learning that a provider is down.
