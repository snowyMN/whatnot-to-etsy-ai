from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app, get_db
from app.models import ImportedItem, ItemAIRecord, ListingImage
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


class FakeListingAIService:
    def regenerate_marketing_strategy(self, db, item):
        if item.ai_record is None:
            item.ai_record = ItemAIRecord(item_id=item.id)
            db.add(item.ai_record)
        item.ai_record.marketing_strategy_json = (
            '{"target_customer":"boho shopper","buyer_intent":[],"positioning_angle":"soft boho blouse","primary_value_proposition":null,'
            '"selling_points":[],"search_keywords":[],"long_tail_keywords":[],"style_keywords":[],"merchandising_notes":[],'
            '"recommended_primary_image_type":null,"social_media_angles":[],"marketplace_notes":[],"warnings":[]}'
        )
        item.ai_record.workflow_steps_json = (
            '[{"task_type":"MARKETING_STRATEGY","model_name":"fake-qwen","prompt_name":"marketing_strategy","prompt_version":"1.0","success":true,"duration_ms":10,"error":null}]'
        )
        db.commit()
        return item.ai_record

    def regenerate_listing_draft(self, db, item):
        if item.ai_record is None:
            item.ai_record = ItemAIRecord(item_id=item.id)
            db.add(item.ai_record)
        item.ai_record.ai_title = "Generated title"
        item.ai_record.ai_description = "Generated description"
        item.ai_record.ai_keywords = '["keyword one"]'
        item.ai_record.marketplace_draft_json = (
            '{"title":"Generated title","description":"Generated description","feature_bullets":[],"keywords":["keyword one"],"condition_statement":null,"buyer_notes":[]}'
        )
        item.ai_record.listing_validation_json = (
            '{"passed":true,"issues":[],"unsupported_claims":[],"warnings":[],"recommended_changes":[]}'
        )
        db.commit()
        return item.ai_record

    def save_marketing_strategy(self, db, item, strategy):
        if item.ai_record is None:
            item.ai_record = ItemAIRecord(item_id=item.id)
            db.add(item.ai_record)
        item.ai_record.marketing_strategy_json = strategy.model_dump_json()
        db.commit()
        return item.ai_record


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
        item.ai_record = ItemAIRecord(
            item_id=1,
            ai_brand="Vintage Brand",
            ai_item_type="shirt",
            ai_keywords='["vintage tee"]',
            marketing_strategy_json=(
                '{"target_customer":"casual buyer","buyer_intent":["vintage tee"],"positioning_angle":"easy casual staple",'
                '"primary_value_proposition":"wearable everyday vintage piece","selling_points":["soft feel"],'
                '"search_keywords":["vintage tee"],"long_tail_keywords":[],"style_keywords":[],"merchandising_notes":[],'
                '"recommended_primary_image_type":null,"social_media_angles":[],"marketplace_notes":[],"warnings":[]}'
            ),
            listing_validation_json='{"passed":true,"issues":[],"unsupported_claims":[],"warnings":[],"recommended_changes":[]}',
        )
        image = ListingImage(
            id=1,
            item_id=1,
            processed_path="data/images/test.jpg",
            local_original_path="data/images/test.jpg",
            selected_variant="original",
        )
        item.images = [image]
        self.session.add(item)
        self.session.add(item.ai_record)
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

    @patch("app.main.LocalListingAIService", return_value=FakeListingAIService())
    def test_regenerate_marketing_strategy_route(self, _service):
        response = self.client.post("/items/1/marketing-strategy/regenerate")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai"]["marketing_strategy"]["target_customer"], "boho shopper")

    @patch("app.main.LocalListingAIService", return_value=FakeListingAIService())
    def test_regenerate_listing_route(self, _service):
        response = self.client.post("/items/1/listing/regenerate")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai"]["draft"]["title"], "Generated title")

    @patch("app.main.LocalListingAIService", return_value=FakeListingAIService())
    def test_save_marketing_strategy_route(self, _service):
        response = self.client.put(
            "/items/1/marketing-strategy",
            json={
                "target_customer": "edited customer",
                "buyer_intent": ["edited intent"],
                "positioning_angle": "edited angle",
                "primary_value_proposition": "edited value",
                "selling_points": ["point a"],
                "search_keywords": ["keyword a"],
                "long_tail_keywords": [],
                "style_keywords": [],
                "merchandising_notes": [],
                "recommended_primary_image_type": None,
                "social_media_angles": [],
                "marketplace_notes": [],
                "warnings": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ai"]["marketing_strategy"]["target_customer"], "edited customer")


if __name__ == "__main__":
    unittest.main()
