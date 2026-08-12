from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import cast

from app.models import ListingImage
from app.schemas_ai import ImageValidationResult
from app.services.llm_provider import LLMImageInput, LLMProviderError, LLMRequest
from app.services.lm_studio_provider import LMStudioProvider


IMAGE_COMPARE_SYSTEM_PROMPT = """
You compare an original resale product image against an edited image.
Preserve factual product condition above aesthetics.
Return JSON only.
Flag any possible changes to stains, holes, logos, labels, color, shape, texture, missing parts, or visible wear.
""".strip()


def _path_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/jpeg"
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


class ImageValidationService:
    def __init__(self, provider: LMStudioProvider | None = None) -> None:
        self.provider = provider or LMStudioProvider()

    def validate_image_pair(self, image: ListingImage) -> ImageValidationResult:
        original_path_str = cast(str | None, image.processed_path) or cast(str | None, image.local_original_path)
        enhanced_path_str = cast(str | None, image.enhanced_path)
        if not original_path_str or not enhanced_path_str:
            raise ValueError("Both original/processed and enhanced image paths are required.")

        original_path = Path(original_path_str)
        enhanced_path = Path(enhanced_path_str)
        if not original_path.exists() or not enhanced_path.exists():
            raise ValueError("Image files required for validation are missing.")

        request = LLMRequest(
            system_prompt=IMAGE_COMPARE_SYSTEM_PROMPT,
            user_prompt=(
                "Compare the first image (original) with the second image (enhanced). "
                "Return strict JSON with keys: passed, confidence, possible_changes, "
                "condition_details_preserved, brand_logo_preserved, color_preserved, notes."
            ),
            images=[
                LLMImageInput(data_url=_path_to_data_url(original_path)),
                LLMImageInput(data_url=_path_to_data_url(enhanced_path)),
            ],
            max_tokens=400,
            temperature=0.0,
        )
        raw = self.provider.generate_json(request)
        return ImageValidationResult.model_validate(raw)

    def persist_validation_result(self, image: ListingImage, result: ImageValidationResult) -> None:
        setattr(image, "ai_validation", json.dumps(result.model_dump()))
        setattr(image, "validation_confidence", result.confidence)
        setattr(image, "validation_status", "NEEDS_REVIEW" if not result.passed else "VALIDATED")
