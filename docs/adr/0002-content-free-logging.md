# ADR 0002: Logs carry metadata, never content

Status: accepted (2026-11-05)

Prompts and completions routinely contain personal or confidential data. The access log therefore records only request id, method, path, status, duration, provider and attempt outcomes. Provider adapters raise errors whose messages contain a status code, never a body. Validation errors report the location and type of a problem, not the submitted value. Unexpected exceptions become a generic `500` and are not echoed.

A test sends a marker string as prompt and system message and asserts it appears nowhere in the log record or rendered log text.

Trade-off: debugging a bad completion needs the caller's own copy of the request. That is the cost of not storing user content by default.
