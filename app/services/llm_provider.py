from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMImageInput:
    data_url: str


@dataclass(slots=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    images: list[LLMImageInput] = field(default_factory=list)
    max_tokens: int | None = None
    temperature: float | None = None


class LLMProviderError(RuntimeError):
    """Raised when a local LLM provider cannot complete a request."""


class LLMProvider(ABC):
    @abstractmethod
    def generate_text(self, request: LLMRequest) -> str:
        """Generate raw text output from a local LLM provider."""

    @abstractmethod
    def generate_json(self, request: LLMRequest) -> dict[str, Any]:
        """Generate JSON output from a local LLM provider."""
