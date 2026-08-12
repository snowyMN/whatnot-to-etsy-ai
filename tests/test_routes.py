from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app, get_db
from app.models import ImportedItem, ListingImage
from app.schemas_ai import ImageValidationResult


class FakeEnhancementService:
    def enhance_image(self, db, item, image, force_provider="auto", output_width=1024, output_height=1024):
        image.enhanced_path = image.processed_path
        image.enhancement_status = "ENHANCED"
        image.validation_status = "VALIDATED"
        db.commit()
        return type(
            "Result",
            (),
            {
                "item_id": item.id,
                "image_id": image.id,
                "enhancement_status": image.enhancement_status,
                "validation_status": image.validation_status,
                "processing_path": "deterministic",
                "enhanced_path": image.enhanced_path,
            },
        )()


class FakeValidationService:
    def validate_image_pair(self, image):
        return ImageValidationResult(
            passed=True,
            confidence=0.9,
            possible_changes=[],
            condition_details_preserved=True,
            brand_logo_preserved=True,
            color_preserved=True,
            notes=[],
        )

    def persist_validation_result(self, image, result):
        image.ai_validation = result.model_dump_json()
        image.validation_status = "VALIDATED"


class RoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.session = TestingSessionLocal()

        def override_get_db():
            try:
                yield self.session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        item = ImportedItem(id=1, source_url="https://example.com/item", title="Vintage tee")
        image = ListingImage(
            id=1,
            item_id=1,
            processed_path="data/images/test.jpg",
            local_original_path="data/images/test.jpg",
            selected_variant="original",
        )
        item.images = [image]
        self.session.add(item)
        self.session.add(image)
        self.session.commit()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)

    @patch("app.main.ImageEnhancementService", return_value=FakeEnhancementService())
    def test_enhance_image_route(self, _service):
        response = self.client.post("/items/1/images/1/enhance", json={"force_provider": "deterministic"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["processing_path"], "deterministic")

    @patch("app.main.ImageValidationService", return_value=FakeValidationService())
    def test_validate_image_route(self, _service):
        response = self.client.post("/items/1/images/1/validate")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["images"][0]["validation_status"], "VALIDATED")


if __name__ == "__main__":
    unittest.main()
