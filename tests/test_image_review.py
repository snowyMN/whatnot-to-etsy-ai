from __future__ import annotations

import unittest

from app.models import ImportedItem, ListingImage
from app.services.image_review import ImageReviewService


class FakeDB:
    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:
        return None


class ImageReviewServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDB()
        self.item = ImportedItem(id=1, source_url="https://example.com/item")
        self.image1 = ListingImage(id=10, item_id=1, selected_variant="original")
        self.image2 = ListingImage(id=11, item_id=1, selected_variant="original")
        self.item.images = [self.image1, self.image2]
        self.service = ImageReviewService()

    def test_select_primary_marks_only_target(self) -> None:
        self.service.select_primary(self.db, self.item, 11)
        self.assertFalse(self.image1.is_primary_selected)
        self.assertTrue(self.image2.is_primary_selected)

    def test_reject_image_resets_publish_choice(self) -> None:
        self.image1.selected_variant = "enhanced"
        self.image1.selected_for_publish = True
        self.service.reject_image(self.db, self.item, 10)
        self.assertEqual(self.image1.validation_status, "REJECTED")
        self.assertEqual(self.image1.selected_variant, "original")
        self.assertFalse(self.image1.selected_for_publish)


if __name__ == "__main__":
    unittest.main()
