from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import AIExecution, ImportedItem, ListingImage
from app.services.listing_ai import LocalListingAIService


class FakeWorkflowProvider:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.requests = []
        self.model = "fake-qwen"

    def generate_text(self, request):
        raise NotImplementedError()

    def generate_json(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("No fake responses remaining for workflow request.")
        return self.responses.pop(0)


class ListingAIWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.session = TestingSessionLocal()

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_enhance_item_persists_strategy_validation_and_execution_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.jpg"
            Image.new("RGB", (700, 700), color=(220, 210, 200)).save(source_path, format="JPEG")

            item = ImportedItem(
                id=1,
                source_url="https://example.com/item/1",
                title="Free People embroidered top",
                size="M",
                condition="Pre-owned",
                description_notes="Cream embroidered blouse with long sleeves.",
            )
            image = ListingImage(
                id=1,
                item_id=1,
                processed_path=str(source_path),
                local_original_path=str(source_path),
                selected_variant="original",
            )
            item.images = [image]
            self.session.add(item)
            self.session.add(image)
            self.session.commit()

            provider = FakeWorkflowProvider(
                responses=[
                    {
                        "quality_score": 0.92,
                        "recommended_as_primary": True,
                        "issues": [],
                        "recommended_operations": ["exposure_adjustment"],
                        "product_condition_visible": [],
                        "do_not_modify": [],
                        "warnings": [],
                        "confidence": 0.95,
                    },
                    {
                        "brand": "Free People",
                        "category": "women",
                        "item_type": "blouse",
                        "gender": "women",
                        "size": "M",
                        "primary_color": "cream",
                        "secondary_colors": [],
                        "pattern": "embroidered",
                        "style": ["boho", "romantic"],
                        "material": None,
                        "neckline": None,
                        "sleeve_type": "long sleeve",
                        "fit": None,
                        "features": ["embroidered detailing"],
                        "condition_summary": "Pre-owned with no obvious visible flaws in the provided image.",
                        "visible_defects": [],
                        "keywords": ["Free People blouse"],
                        "unknown_fields": ["material"],
                        "warnings": [],
                        "confidence": {"overall": 0.94, "by_field": {"brand": 0.98, "item_type": 0.95}},
                    },
                    {
                        "target_customer": "buyer looking for feminine boho wardrobe pieces",
                        "buyer_intent": ["Free People blouse", "embroidered boho top"],
                        "positioning_angle": "romantic boho layering piece",
                        "primary_value_proposition": "recognizable brand with versatile neutral styling",
                        "selling_points": ["Free People brand", "embroidered detailing", "cream color"],
                        "search_keywords": ["Free People blouse", "boho blouse", "embroidered top"],
                        "long_tail_keywords": ["Free People embroidered cream blouse"],
                        "style_keywords": ["boho", "romantic"],
                        "merchandising_notes": ["Lead with embroidery in the title"],
                        "recommended_primary_image_type": "front flat lay or mannequin shot",
                        "social_media_angles": ["neutral boho capsule wardrobe"],
                        "marketplace_notes": ["Keep title readable before adding extra modifiers"],
                        "warnings": [],
                    },
                    {
                        "title": "Free People Embroidered Cream Boho Blouse",
                        "description": "Free People embroidered cream blouse in size M. Soft boho styling with long sleeves and a romantic feel.",
                        "feature_bullets": ["Free People brand", "embroidered detail", "cream colorway"],
                        "keywords": ["Free People blouse", "embroidered top", "boho blouse"],
                        "condition_statement": "Pre-owned condition. Review photos for final assessment.",
                        "buyer_notes": ["Good layering piece for boho styling"],
                    },
                    {
                        "passed": True,
                        "issues": [],
                        "unsupported_claims": [],
                        "warnings": [],
                        "recommended_changes": [],
                    },
                ]
            )

            service = LocalListingAIService(provider=provider)
            summary = service.enhance_item(self.session, item, max_images=1)

            self.session.refresh(item)
            self.assertEqual(summary.status, "NEEDS_REVIEW")
            self.assertTrue(summary.analysis_completed)
            self.assertTrue(summary.draft_completed)
            self.assertFalse(summary.requires_review)
            self.assertIsNotNone(item.ai_record)
            self.assertEqual(item.ai_record.ai_brand, "Free People")
            self.assertIn("target_customer", json.loads(item.ai_record.marketing_strategy_json))
            self.assertIn("passed", json.loads(item.ai_record.listing_validation_json))
            self.assertEqual(len(json.loads(item.ai_record.workflow_steps_json)), 4)

            executions = self.session.query(AIExecution).order_by(AIExecution.id.asc()).all()
            self.assertEqual(len(executions), 4)
            self.assertEqual(executions[0].task_type, "PRODUCT_ANALYSIS")
            self.assertEqual(executions[1].task_type, "MARKETING_STRATEGY")
            self.assertEqual(executions[2].task_type, "LISTING_WRITER")
            self.assertEqual(executions[3].task_type, "LISTING_VALIDATOR")
            self.assertIn('"verified_product_analysis"', provider.requests[2].user_prompt)
            self.assertIn('"Free People"', provider.requests[2].user_prompt)


if __name__ == "__main__":
    unittest.main()