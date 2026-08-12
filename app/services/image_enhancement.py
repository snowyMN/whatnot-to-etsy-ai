from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from app.config import IMAGE_JPEG_QUALITY, IMAGE_STORAGE_DIR
from app.models import ImportedItem, ListingImage
from app.schemas_ai import ImageEnhancementResult
from app.services.comfyui_image_provider import ComfyUIImageEditingProvider
from app.services.image_editing_provider import ImageEditRequest, ImageEditingProviderError
from app.services.image_validation import ImageValidationService


SEMANTIC_OPERATIONS = {
    "background_cleanup",
    "background_replacement",
    "complex_background_cleanup",
    "semantic_edit",
    "relighting",
}


@dataclass(slots=True)
class EnhancementExecutionResult:
    item_id: int
    image_id: int
    enhancement_status: str
    validation_status: str
    processing_path: str
    enhanced_path: str | None


class ImageEnhancementService:
    def __init__(
        self,
        workflow_template_path: str = "app/ai_workflows/flux_product_edit.json",
        prompt_template_path: str = "app/prompts/flux_product_safe_prompt.txt",
        output_dir: str = IMAGE_STORAGE_DIR,
        validation_service: ImageValidationService | None = None,
    ) -> None:
        self.workflow_template_path = workflow_template_path
        self.prompt_template_path = Path(prompt_template_path)
        self.output_dir = Path(output_dir)
        self.validation_service = validation_service or ImageValidationService()

    def _load_prompt_template(self) -> str:
        if not self.prompt_template_path.exists():
            raise ValueError(f"Prompt template not found: {self.prompt_template_path}")
        return self.prompt_template_path.read_text(encoding="utf-8").strip()

    def _build_prompt(self, image: ListingImage) -> str:
        prompt = self._load_prompt_template()
        operations: list[str] = []
        if image.ai_analysis:
            try:
                payload = json.loads(image.ai_analysis)
                operations = payload.get("recommended_operations", []) or []
            except json.JSONDecodeError:
                operations = []
        if operations:
            prompt += "\n\nRequested safe presentation operations: " + ", ".join(operations)
        return prompt

    def _recommended_operations(self, image: ListingImage) -> list[str]:
        if not image.ai_analysis:
            return []
        try:
            payload = json.loads(image.ai_analysis)
        except json.JSONDecodeError:
            return []
        operations = payload.get("recommended_operations", []) or []
        return [op for op in operations if isinstance(op, str)]

    def _deterministic_edit(self, source_path: Path, destination_path: Path, operations: list[str]) -> None:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source_path) as base_image:
            image = ImageOps.exif_transpose(base_image).convert("RGB")

            if "exposure_adjustment" in operations:
                image = ImageEnhance.Brightness(image).enhance(1.06)
                image = ImageEnhance.Contrast(image).enhance(1.03)

            if "white_balance" in operations:
                image = ImageOps.autocontrast(image)

            if "sharpen" in operations:
                image = image.filter(ImageFilter.SHARPEN)

            # Keep framing safe: pad to square without cropping away defects.
            if "crop" in operations or "reframe" in operations:
                square_size = max(image.size)
                image = ImageOps.pad(
                    image,
                    (square_size, square_size),
                    color=(246, 241, 233),
                    centering=(0.5, 0.5),
                )

            image.save(destination_path, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)

    def _should_use_comfy(self, operations: list[str], force_provider: str) -> bool:
        if force_provider == "comfyui":
            return True
        if force_provider == "deterministic":
            return False
        return any(operation in SEMANTIC_OPERATIONS for operation in operations)

    def _provider(self, item: ImportedItem) -> ComfyUIImageEditingProvider:
        return ComfyUIImageEditingProvider(
            workflow_template_path=self.workflow_template_path,
            output_dir=str(Path(IMAGE_STORAGE_DIR) / f"item_{item.id}"),
        )

    def enhance_image(
        self,
        db: Session,
        item: ImportedItem,
        image: ListingImage,
        *,
        force_provider: str = "auto",
        output_width: int = 1024,
        output_height: int = 1024,
    ) -> EnhancementExecutionResult:
        source_path_str = image.processed_path or image.local_original_path
        if not source_path_str:
            raise ValueError("No local source image is available for enhancement.")

        source_path = Path(source_path_str)
        if not source_path.exists():
            raise ValueError(f"Source image does not exist: {source_path}")

        operations = self._recommended_operations(image)
        target_dir = Path(IMAGE_STORAGE_DIR) / f"item_{item.id}"
        target_dir.mkdir(parents=True, exist_ok=True)
        image_order = cast(int | None, image.image_order) or 0
        enhanced_path = target_dir / f"enhanced_{image_order:02d}.jpg"

        processing_path = "deterministic"
        image.enhancement_status = "ENHANCEMENT_REQUESTED"
        db.commit()

        if self._should_use_comfy(operations, force_provider):
            processing_path = "comfyui"
            try:
                provider = self._provider(item)
                result = provider.edit_image(
                    ImageEditRequest(
                        source_image_path=source_path,
                        prompt=self._build_prompt(image),
                        output_width=output_width,
                        output_height=output_height,
                    )
                )
                enhanced_path = result.output_image_path
            except ImageEditingProviderError:
                # Fall back to deterministic processing on provider failure.
                processing_path = "deterministic-fallback"
                self._deterministic_edit(source_path, enhanced_path, operations)
        else:
            self._deterministic_edit(source_path, enhanced_path, operations)

        image.enhanced_path = str(enhanced_path)
        image.enhancement_operations = json.dumps(
            {
                "processing_path": processing_path,
                "recommended_operations": operations,
            }
        )
        image.enhancement_status = "ENHANCED"

        result = self.validation_service.validate_image_pair(image)
        self.validation_service.persist_validation_result(image, result)
        db.commit()
        db.refresh(image)

        return EnhancementExecutionResult(
            item_id=item.id,
            image_id=image.id,
            enhancement_status=image.enhancement_status,
            validation_status=image.validation_status,
            processing_path=processing_path,
            enhanced_path=image.enhanced_path,
        )
