# Running agent-harness through llm-gateway

Both projects are offline-first and OpenAI-compatible at the edges, so the harness's existing
`OpenAICompatModel` can use the gateway as its endpoint with no harness change: set
`base_url` to `http://127.0.0.1:<port>/v1`. Design notes and limits: [ADR 0003](../adr/0003-openai-compatible-chat-endpoint.md).

## Reproduce (no keys, no network beyond loopback)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e . "agent-harness @ git+https://github.com/jorgitobg/agent-harness@40548b516790940430baf869bede12eee43b3c2a"
python docs/integration/harness_through_gateway.py
```

The script starts the gateway on an ephemeral loopback port with two fake providers (`primary` is down,
`backup` answers; breaker threshold 2), runs three harness tasks, and reads back the gateway's access log.
Real output (timings and request ids vary per run; the first three lines are the gateway's own log):

```text
{"attempts": ["unavailable", "ok"], "duration_ms": 2.6, "level": "info", "method": "POST", "path": "/v1/chat/completions", "provider": "backup", "request_id": "7c54724bdf844beaa63a61d58068982a", "status": 200}
{"attempts": ["unavailable", "ok"], "duration_ms": 1.2, "level": "info", "method": "POST", "path": "/v1/chat/completions", "provider": "backup", "request_id": "faa8af8cb76f412b90e0e9d60c47c628", "status": 200}
{"attempts": ["circuit_open", "ok"], "duration_ms": 0.8, "level": "info", "method": "POST", "path": "/v1/chat/completions", "provider": "backup", "request_id": "e7cc3ab3e9fb48b59c3c4ceaa5836db5", "status": 200}
{
  "attempts_per_request": [
    [
      "unavailable",
      "ok"
    ],
    [
      "unavailable",
      "ok"
    ],
    [
      "circuit_open",
      "ok"
    ]
  ],
  "backup_calls": 3,
  "content_in_logs": false,
  "primary_calls": 2,
  "runs": [
    {
      "answer": "[backup] completion for a 15-character prompt",
      "stop": "final_answer"
    },
    {
      "answer": "[backup] completion for a 14-character prompt",
      "stop": "final_answer"
    },
    {
      "answer": "[backup] completion for a 15-character prompt",
      "stop": "final_answer"
    }
  ]
}
```

What it shows: requests 1 and 2 fall back from `primary` to `backup`; after two failures the breaker opens and
request 3 skips `primary` without calling it (`primary_calls: 2`, `backup_calls: 3`); no task text or system
prompt appears in the logs (`content_in_logs: false`). `tests/test_harness_integration.py` asserts all of it
and is skipped when agent-harness is not installed.

## Limits

The harness requires Python 3.12+, so the integration test runs on the 3.13 CI job and is skipped on 3.11. Text only: no tool calling, no streaming, no token usage (see the ADR). The providers are fakes, so this
demonstrates control flow, not model behaviour or latency. The harness is pinned by commit SHA.
