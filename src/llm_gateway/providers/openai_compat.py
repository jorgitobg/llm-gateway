from __future__ import annotations

from typing import Any

import httpx

from llm_gateway.errors import ProviderRejected, ProviderTimeout, ProviderUnavailable
from llm_gateway.providers.base import CompletionRequest


class OpenAICompatProvider:
    """Chat-completions client for any OpenAI-compatible endpoint (hosted or local).

    Error messages carry the status code only: never the request or response body.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        name: str = "openai-compatible",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient()

    async def complete(self, request: CompletionRequest) -> str:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        try:
            response = await self._client.post(self._url, json=body, headers=self._headers)
        except httpx.TimeoutException as error:
            raise ProviderTimeout("upstream timed out") from error
        except httpx.HTTPError as error:
            raise ProviderUnavailable("upstream transport error") from error
        status = response.status_code
        if status == 429 or status >= 500:
            raise ProviderUnavailable(f"upstream status {status}")
        if status >= 400:
            raise ProviderRejected(f"upstream status {status}")
        try:
            choice = response.json()["choices"][0]
            content = choice["message"]["content"]
            finish = choice.get("finish_reason")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise ProviderUnavailable("upstream returned an unusable response") from error
        if content is None or (isinstance(content, str) and not content.strip()):
            # Reasoning models can spend the whole token budget thinking and return no text.
            reason = "token budget exhausted" if finish == "length" else "empty completion"
            raise ProviderUnavailable(f"upstream returned no text ({reason})")
        if not isinstance(content, str):
            raise ProviderUnavailable("upstream returned an unusable response")
        return content

    async def aclose(self) -> None:
        await self._client.aclose()
