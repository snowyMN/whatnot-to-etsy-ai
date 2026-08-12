from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ImageEditRequest:
    source_image_path: Path
    prompt: str
    negative_prompt: str | None = None
    output_width: int = 1024
    output_height: int = 1024
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageEditResult:
    output_image_path: Path
    provider: str
    model: str
    job_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ImageEditingProviderError(RuntimeError):
    """Raised when image editing provider execution fails."""


class ImageEditingProvider(ABC):
    @abstractmethod
    def edit_image(self, request: ImageEditRequest) -> ImageEditResult:
        """Create an edited image artifact from a source image and prompt."""
