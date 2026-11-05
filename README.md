# llm-gateway

A small HTTP service that sits in front of one or more language-model providers and makes the unglamorous parts explicit: bounded requests, a provider fallback chain, a per-provider circuit breaker, and logs that never contain prompt or response text.

**What it is today (v0.1):** a FastAPI service with a provider port, a deterministic offline provider with simulated failures, and an adapter for any OpenAI-compatible endpoint (hosted, llama.cpp, Ollama, OpenRouter). The offline demo needs no network and no keys.

**What it is not:** it does not authenticate callers, rate-limit them, stream responses, count tokens or cost, or run a model. Run it behind your own gateway or reverse proxy. The OpenAI-compatible adapter is covered by mocked-transport tests in CI and was also checked once against a live hosted model (see below). No latency or throughput claims are made.

## Quickstart

Python 3.11+.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python -m llm_gateway.demo          # offline, deterministic
pytest                              # coverage gate: 90 percent
uvicorn --factory llm_gateway.app:create_app
```

```bash
curl -s localhost:8000/v1/generate -H 'content-type: application/json' -d '{"prompt":"hello"}'
```

`create_app` is a factory on purpose: configuration is read from the environment when the app is created, not at import time. Copy `.env.example` for the settings (all optional for the offline demo).

## Demo output

`python -m llm_gateway.demo` (captured from a real run; the request ids are fixed so the output is reproducible):

```text

## 1. Oversized prompt: rejected before any provider is called
-> 413
{
  "error": {
    "code": "payload_too_large",
    "message": "Prompt exceeds the configured limit",
    "request_id": "demo-1"
  }
}

## 2. Unknown field: rejected by the schema
-> 422
{
  "error": {
    "code": "invalid_request",
    "details": [
      {
        "loc": [
          "body",
          "debug"
        ],
        "type": "extra_forbidden"
      }
    ],
    "message": "Request failed validation",
    "request_id": "demo-2"
  }
}

## 3. Primary is down: the backup answers (failure 1 of 2)
-> 200
{
  "attempts": [
    {
      "outcome": "unavailable",
      "provider": "primary"
    },
    {
      "outcome": "ok",
      "provider": "backup"
    }
  ],
  "prompt_version": null,
  "provider": "backup",
  "text": "[backup] completion for a 43-character prompt",
  "truncated": false
}

## 4. Versioned summarize prompt; marker injection neutralised (failure 2 of 2)
-> 200
{
  "attempts": [
    {
      "outcome": "unavailable",
      "provider": "primary"
    },
    {
      "outcome": "ok",
      "provider": "backup"
    }
  ],
  "prompt_version": "summarize/v1",
  "provider": "backup",
  "text": "[backup] completion for a 193-character prompt",
  "truncated": false
}

## 5. Circuit breaker open: the primary is skipped without being called
-> 200
{
  "attempts": [
    {
      "outcome": "circuit_open",
      "provider": "primary"
    },
    {
      "outcome": "ok",
      "provider": "backup"
    }
  ],
  "prompt_version": null,
  "provider": "backup",
  "text": "[backup] completion for a 5-character prompt",
  "truncated": false
}

primary provider calls: 2 (the third request never reached it)
backup provider calls: 3
```

## Checked against a live model

The test suite never touches the network. As a one-off check on 2026-11-05 (outside CI, since it depends on a third party), the adapter was run through OpenRouter against a free-tier reasoning model (`nvidia/nemotron-3.5-lightning:free`):

- `POST /v1/generate` returned the expected text through the real service, and the server log held neither the API key nor the prompt.
- With `LLM_GATEWAY_MAX_OUTPUT_TOKENS=512` the model spent the whole budget on hidden reasoning and returned **empty text** in 6 of 6 attempts. The adapter now reports this as a retryable failure (`token budget exhausted`) instead of an opaque "unusable response", so the chain falls back to the next provider. This was found by the live check; the mocks could not have shown it.
- With `LLM_GATEWAY_MAX_OUTPUT_TOKENS=2048`, 6 of 6 summarize calls succeeded.

Reasoning models need a larger output budget than plain chat models. One free model on one day is an anecdote, not a benchmark.

## Endpoints

- `POST /v1/generate` with `{"prompt", "system"?}`
- `POST /v1/summarize` with `{"text"}`: renders the versioned prompt `summarize/v1`
- `GET /health` (process is up) and `GET /ready` (configured providers)

Every response carries an `x-request-id`. A caller-supplied id is kept only if it is short and log-safe; otherwise a new one is minted.

## Design

- **Bounded by default.** Prompt length, body size (checked from `Content-Length` before parsing), output tokens and output characters are all capped; unknown request fields are rejected.
- **Failure is a first-class result.** A timeout, outage, `429` or malformed response moves on to the next provider. A `4xx` rejection stops the chain: another provider would get the same bad request. When every provider fails the caller gets `503` with a stable error code.
- **Circuit breaker per provider.** After N consecutive failures a provider is skipped for a cooldown period, so a dead upstream costs nothing instead of a timeout on every request.
- **Content-free logging.** One JSON line per request: id, method, path, status, duration, provider and attempt outcomes. Prompts, system messages, completions and upstream bodies are never logged. A test asserts this.
- **Prompt hygiene, honestly scoped.** The summarize template wraps user text in delimiters and neutralises look-alike markers. That reduces, but does not eliminate, prompt injection.

Decisions: [ADR 0001](docs/adr/0001-provider-port-and-fallback.md), [ADR 0002](docs/adr/0002-content-free-logging.md). Specification: [docs/spec/0001-llm-gateway.md](docs/spec/0001-llm-gateway.md).

## Limitations

- In-memory breaker state: it is per process, so several workers each learn about an outage separately.
- No retry of the same provider and no hedging; the first failure moves on.
- The offline provider shows the control flow, not model behaviour.
- Output tokens are capped but reasoning tokens count against the cap on some models (see above).
- Character limits stand in for token limits.

## Layout

- `src/llm_gateway/app.py`: FastAPI factory, middleware, error mapping
- `src/llm_gateway/providers/`: port, offline provider, OpenAI-compatible adapter, chain and breaker
- `src/llm_gateway/settings.py`: validated, environment-driven configuration
- `src/llm_gateway/prompts.py`: versioned prompt rendering
- `tests/`: API, adapter, settings and logging tests (no network)

Apache-2.0. AI-assisted, human-reviewed.
