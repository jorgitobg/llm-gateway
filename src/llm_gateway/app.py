from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from llm_gateway import __version__
from llm_gateway.errors import GatewayError
from llm_gateway.logging_setup import ACCESS_LOGGER, configure_logging
from llm_gateway.prompts import SUMMARIZE_VERSION, render_summarize
from llm_gateway.providers import AllProvidersFailed, CompletionRequest, ProviderChain, build_chain
from llm_gateway.providers.chain import Attempt
from llm_gateway.schemas import (
    AttemptOut,
    CompletionResponse,
    GenerateRequest,
    SummarizeRequest,
)
from llm_gateway.settings import Settings

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_log = logging.getLogger(ACCESS_LOGGER)


def _request_id(header: str | None) -> str:
    """Accept a caller-supplied id only if it is short and log-safe; otherwise mint one."""
    if header and _REQUEST_ID.fullmatch(header):
        return header
    return uuid.uuid4().hex


def _error(status: int, code: str, message: str, request_id: str, **extra: object) -> JSONResponse:
    body: dict[str, object] = {"code": code, "message": message, "request_id": request_id}
    body.update(extra)
    return JSONResponse({"error": body}, status_code=status)


def create_app(*, chain: ProviderChain | None = None, settings: Settings | None = None) -> FastAPI:
    configure_logging()
    cfg = settings or Settings.from_env(os.environ)
    active = chain or build_chain(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield
        await active.aclose()

    app = FastAPI(title="LLM Gateway", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def access(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request.headers.get("x-request-id"))
        request.state.request_id = request_id
        request.state.provider = None
        request.state.attempts = list[str]()
        started = time.perf_counter()
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cfg.max_body_bytes:
            response: Response = _error(
                413, "payload_too_large", "Request body is too large", request_id
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                response = _error(500, "internal_error", "Unexpected server error", request_id)
        response.headers["x-request-id"] = request_id
        attempts: list[str] = request.state.attempts
        _log.info(
            "request",
            extra={
                "event": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "provider": request.state.provider,
                    "attempts": attempts,
                }
            },
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in e["loc"]], "type": e["type"]} for e in exc.errors()]
        return _error(
            422, "invalid_request", "Request failed validation", request.state.request_id,
            details=details,
        )  # fmt: skip

    @app.exception_handler(GatewayError)
    async def _gateway(request: Request, exc: GatewayError) -> JSONResponse:
        attempts: tuple[Attempt, ...] = getattr(exc, "attempts", ())
        request.state.attempts = [a.outcome for a in attempts]
        return _error(exc.status, exc.code, exc.message, request.state.request_id)

    async def _complete(
        request: Request, prompt: str, system: str | None, version: str | None
    ) -> CompletionResponse:
        if len(prompt) > cfg.max_prompt_chars or (system and len(system) > cfg.max_prompt_chars):
            raise GatewayError(413, "payload_too_large", "Prompt exceeds the configured limit")
        result = await active.run(CompletionRequest(prompt, system, cfg.max_output_tokens))
        request.state.provider = result.provider
        request.state.attempts = [a.outcome for a in result.attempts]
        text = result.text[: cfg.max_output_chars]
        return CompletionResponse(
            text=text,
            provider=result.provider,
            truncated=len(result.text) > len(text),
            prompt_version=version,
            attempts=[AttemptOut(provider=a.provider, outcome=a.outcome) for a in result.attempts],
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/ready")
    async def ready() -> dict[str, object]:
        return {"status": "ready", "providers": list(active.provider_names)}

    @app.post("/v1/generate", response_model=CompletionResponse)
    async def generate(request: Request, body: GenerateRequest) -> CompletionResponse:
        return await _complete(request, body.prompt, body.system, None)

    @app.post("/v1/summarize", response_model=CompletionResponse)
    async def summarize(request: Request, body: SummarizeRequest) -> CompletionResponse:
        if len(body.text) > cfg.max_prompt_chars:
            raise GatewayError(413, "payload_too_large", "Text exceeds the configured limit")
        return await _complete(request, render_summarize(body.text), None, SUMMARIZE_VERSION)

    return app


__all__ = ["AllProvidersFailed", "create_app"]
