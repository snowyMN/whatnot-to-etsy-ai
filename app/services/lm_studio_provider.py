from __future__ import annotations

import json
import time
from typing import Any

from openai import OpenAI

from app.config import (
    LOCAL_LLM_BASE_URL,
    LOCAL_LLM_MAX_RETRIES,
    LOCAL_LLM_MAX_TOKENS,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_TEMPERATURE,
    LOCAL_LLM_TIMEOUT,
    OPENAI_API_KEY,
)
from app.services.llm_provider import LLMProvider, LLMProviderError, LLMRequest


class LMStudioProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = LOCAL_LLM_BASE_URL,
        model: str = LOCAL_LLM_MODEL,
        timeout_seconds: int = LOCAL_LLM_TIMEOUT,
        max_retries: int = LOCAL_LLM_MAX_RETRIES,
        default_max_tokens: int = LOCAL_LLM_MAX_TOKENS,
        default_temperature: float = LOCAL_LLM_TEMPERATURE,
        api_key: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.default_max_tokens = default_max_tokens
        self.default_temperature = default_temperature
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key or OPENAI_API_KEY or "lm-studio",
            timeout=timeout_seconds,
        )

    def _build_messages(self, request: LLMRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": request.system_prompt}]

        user_content: list[dict[str, Any]] = [{"type": "text", "text": request.user_prompt}]
        for image in request.images:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image.data_url},
                }
            )

        messages.append({"role": "user", "content": user_content})
        return messages

    def generate_text(self, request: LLMRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self._build_messages(request),
                    max_tokens=request.max_tokens or self.default_max_tokens,
                    temperature=(
                        self.default_temperature
                        if request.temperature is None
                        else request.temperature
                    ),
                )
                content = response.choices[0].message.content
                if not content:
                    raise LLMProviderError("LM Studio returned an empty response.")
                return content
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(0.75 * (attempt + 1), 2.0))

        raise LLMProviderError(f"LM Studio request failed after retries: {last_error}")

    @staticmethod
    def _extract_json_candidate(text: str) -> str:
        stripped = text.strip()

        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            return stripped[start : end + 1]

        return stripped

    def generate_json(self, request: LLMRequest) -> dict[str, Any]:
        text = self.generate_text(request)
        candidate = self._extract_json_candidate(text)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"LM Studio returned invalid JSON: {exc}") from exc
