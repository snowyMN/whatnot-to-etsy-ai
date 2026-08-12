from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.models import ImportedItem, ListingImage
from app.schemas_ai import ImageValidationResult
from app.services.image_enhancement import ImageEnhancementService


class FakeDB:
    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:
        return None


class FakeValidationService:
    def validate_image_pair(self, image: ListingImage) -> ImageValidationResult:
        return ImageValidationResult(
            passed=True,
            confidence=0.95,
            possible_changes=[],
            condition_details_preserved=True,
            brand_logo_preserved=True,
            color_preserved=True,
            notes=[],
        )

    def persist_validation_result(self, image: ListingImage, result: ImageValidationResult) -> None:
        image.ai_validation = json.dumps(result.model_dump())
        image.validation_confidence = result.confidence
        image.validation_status = "VALIDATED"


class ImageEnhancementServiceTests(unittest.TestCase):
    def test_deterministic_enhancement_creates_enhanced_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (600, 400), color=(120, 130, 140)).save(source_path, format="JPEG")

            item = ImportedItem(id=5, source_url="https://example.com/item")
            image = ListingImage(
                id=20,
                item_id=5,
                processed_path=str(source_path),
                ai_analysis=json.dumps({"recommended_operations": ["exposure_adjustment", "sharpen"]}),
                selected_variant="original",
            )

            service = ImageEnhancementService(
                output_dir=temp_dir,
                validation_service=FakeValidationService(),
            )
            result = service.enhance_image(FakeDB(), item, image, force_provider="deterministic")

            self.assertEqual(result.processing_path, "deterministic")
            self.assertEqual(image.enhancement_status, "ENHANCED")
            self.assertEqual(image.validation_status, "VALIDATED")
            self.assertTrue(Path(image.enhanced_path).exists())


if __name__ == "__main__":
    unittest.main()
