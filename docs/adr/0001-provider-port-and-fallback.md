# ADR 0001: Provider port, ordered fallback, per-provider breaker

Status: accepted (2026-11-05)

Handlers depend on a `Provider` protocol (`complete(request) -> str`) and on `ProviderChain`, never on a vendor SDK. Failures are typed (`ProviderTimeout`, `ProviderUnavailable`, `ProviderRejected`) so the chain can decide: retryable failures try the next provider, a rejection stops the chain. A breaker per provider skips a failing upstream for a cooldown. The clock is injected so breaker behaviour is tested without sleeping.

Alternatives considered: retrying the same provider (adds latency during an outage and hides it), a vendor SDK per provider (more dependencies and a harder-to-fake boundary).

Trade-off: breaker state is in process memory, so each worker learns about an outage on its own. A shared store is the next step if that matters; it is deliberately not built before it is needed.
