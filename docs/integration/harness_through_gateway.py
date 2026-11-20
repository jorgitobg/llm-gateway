"""Offline demo: an agent-harness run whose model endpoint is llm-gateway.

Needs the ``agent-harness`` package (see docs/integration/agent-harness.md). No keys, no
network beyond loopback: the gateway listens on 127.0.0.1 and its two providers are fakes.

    python docs/integration/harness_through_gateway.py
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time

import uvicorn
from agent_harness.adapters.openai_compat import OpenAICompatConfig, OpenAICompatModel
from agent_harness.application.agent_loop import AgentLoop
from agent_harness.application.registry import ToolRegistry
from agent_harness.domain.loop import Budget

from llm_gateway.app import create_app
from llm_gateway.logging_setup import ACCESS_LOGGER, JsonFormatter
from llm_gateway.providers import FakeProvider, ProviderChain
from llm_gateway.settings import Settings

SECRET_TASKS = ("task-alpha-5e1f", "task-beta-5e1f", "task-gamma-5e1f")


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def run_demo() -> dict[str, object]:
    primary, backup = FakeProvider("primary", "unavailable"), FakeProvider("backup", "ok")
    chain = ProviderChain(
        [primary, backup], timeout_s=1.0, breaker_threshold=2, breaker_cooldown_s=300.0
    )
    app = create_app(chain=chain, settings=Settings())
    capture = _Capture()
    capture.setFormatter(JsonFormatter())
    logging.getLogger(ACCESS_LOGGER).addHandler(capture)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("gateway did not start")

    try:
        model = OpenAICompatModel(
            OpenAICompatConfig(
                base_url=f"http://127.0.0.1:{port}/v1",
                model="ignored-by-the-gateway",
                system_prompt="Answer briefly.",
                max_tokens=128,
            )
        )
        loop = AgentLoop(model, ToolRegistry(), Budget(max_steps=2, timeout_s=30.0))
        answers = [loop.run(task) for task in SECRET_TASKS]
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        logging.getLogger(ACCESS_LOGGER).removeHandler(capture)

    events = [
        json.loads(line)
        for line in capture.lines
        if json.loads(line).get("path") == "/v1/chat/completions"
    ]
    logged = "\n".join(capture.lines)
    return {
        "runs": [{"stop": r.stop_reason.value, "answer": r.final_answer} for r in answers],
        "attempts_per_request": [e["attempts"] for e in events],
        "primary_calls": primary.calls,
        "backup_calls": backup.calls,
        "content_in_logs": any(t in logged for t in SECRET_TASKS) or "Answer briefly." in logged,
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), indent=2, sort_keys=True))
