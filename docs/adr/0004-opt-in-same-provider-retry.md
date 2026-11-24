# ADR 0004: opt-in same-provider retry

Status: accepted.

ADR 0001 rejected retrying the same provider as the default: it adds latency during an outage and hides it. This ADR keeps that default and adds an opt-in `RetryPolicy` for deployments where short blips are common.

- Default is one attempt: behaviour and outputs are unchanged.
- Only failures the chain already treats as retryable (timeout, 5xx/429, unusable response) are retried. A rejection (4xx) is permanent and stops the chain immediately.
- Bounds: `max_attempts` (1 to 10), a fixed `backoff_s`, and an optional `deadline_s` per provider per request. A retry only starts if time remains after its pause, and every try's timeout (the first included) is capped to the remaining budget.
- Each try is recorded as an `Attempt`; no content is logged or stored.
- Breaker: counts the *final* outcome per provider per request. Counting each try would let one request with 3 tries open a threshold-3 breaker on its own and make retry and breaker fight each other.
- Clock and sleep are injected, so tests never wait.

Worst case latency per provider is `max_attempts x timeout_s` plus backoff unless a deadline is set. No hedging, no jitter, no `Retry-After` handling.
