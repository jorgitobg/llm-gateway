from __future__ import annotations

from importlib import resources

SUMMARIZE_VERSION = "summarize/v1"
_OPEN, _CLOSE = "<<<TEXT", "TEXT>>>"


def _template() -> str:
    return (
        resources.files("llm_gateway")
        .joinpath("prompts/summarize_v1.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def render_summarize(text: str) -> str:
    """Render the summarize prompt. Marker look-alikes in the input are neutralised so the
    text cannot close its own delimiter. This reduces, but does not eliminate, prompt injection."""
    safe = text.replace(_CLOSE, "TEXT> >>").replace(_OPEN, "<<< TEXT")
    return _template().replace("{{ input }}", safe)
