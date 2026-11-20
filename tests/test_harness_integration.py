# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""Runs docs/integration/harness_through_gateway.py. Skipped when agent-harness is absent."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("agent_harness")

SCRIPT = (
    Path(__file__).resolve().parent.parent / "docs" / "integration" / "harness_through_gateway.py"
)


def test_harness_runs_through_the_gateway_with_fallback_and_content_free_logs() -> None:
    spec = importlib.util.spec_from_file_location("harness_through_gateway", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_demo()

    assert [r["stop"] for r in result["runs"]] == ["final_answer"] * 3
    assert all(r["answer"].startswith("[backup]") for r in result["runs"])
    # Two failures open the breaker; the third request never reaches the primary.
    assert result["attempts_per_request"] == [
        ["unavailable", "ok"],
        ["unavailable", "ok"],
        ["circuit_open", "ok"],
    ]
    assert (result["primary_calls"], result["backup_calls"]) == (2, 3)
    assert result["content_in_logs"] is False
