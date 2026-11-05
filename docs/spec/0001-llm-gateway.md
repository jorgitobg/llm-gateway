# Spec 0001: llm-gateway

## Stories

### US1: Bounded requests
- Given a prompt longer than the configured limit, when posted, then the response is `413 payload_too_large` and no provider is called.
- Given a body whose `Content-Length` exceeds the limit, when posted, then it is rejected with `413` before it is parsed.
- Given an unknown field, a blank prompt or a missing field, then the response is `422 invalid_request` listing only the location and type of each error, never the submitted value.
- Given provider output longer than the output limit, then it is truncated and `truncated` is `true`.

### US2: Provider chain
- Given providers A then B and A times out or is unavailable, when a request arrives, then B answers and `attempts` shows `[timeout|unavailable, ok]`.
- Given a provider rejects the request (`4xx`), then the chain stops with `502 upstream_rejected`.
- Given every provider fails, then the response is `503 providers_unavailable`.

### US3: Circuit breaker
- Given N consecutive failures of a provider, then it is skipped (`circuit_open`) without being called until the cooldown elapses; after the cooldown it is tried again and a success resets its failure count.

### US4: OpenAI-compatible adapter
- Given an endpoint that returns a chat completion, then the text is returned; `429` and `5xx` are retryable, other `4xx` are rejections, timeouts and malformed bodies are retryable.
- Error messages carry the status code only, never a request or response body.

### US5: Content-free observability
- Given any request, then exactly one JSON log line is emitted with id, method, path, status, duration, provider and attempt outcomes, and no prompt, system message or completion text.

### US6: Offline demo
- Given no network and no keys, when `python -m llm_gateway.demo` runs, then it shows rejection, fallback, versioned summarisation and the breaker, deterministically.

## Non-goals
Authentication, rate limiting, streaming, token accounting, cost tracking, persistence, running models.
