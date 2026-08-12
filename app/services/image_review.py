from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ImportedItem, ListingImage


class ImageReviewError(ValueError):
    """Raised when an image review action cannot be completed."""


class ImageReviewService:
    def _find_image(self, item: ImportedItem, image_id: int) -> ListingImage:
        for image in item.images:
            if image.id == image_id:
                return image
        raise ImageReviewError("Image not found for this item.")

    def select_primary(self, db: Session, item: ImportedItem, image_id: int) -> ImportedItem:
        target = self._find_image(item, image_id)
        for image in item.images:
            image.is_primary_selected = image.id == target.id
        db.commit()
        db.refresh(item)
        return item

    def choose_original(self, db: Session, item: ImportedItem, image_id: int) -> ImportedItem:
        target = self._find_image(item, image_id)
        target.selected_variant = "original"
        target.selected_for_publish = False
        if target.validation_status == "REJECTED":
            target.validation_status = "PENDING"
        db.commit()
        db.refresh(item)
        return item

    def choose_enhanced(self, db: Session, item: ImportedItem, image_id: int) -> ImportedItem:
        target = self._find_image(item, image_id)
        if not target.enhanced_path:
            raise ImageReviewError("No enhanced image exists for this asset yet.")
        target.selected_variant = "enhanced"
        target.selected_for_publish = False
        target.validation_status = "NEEDS_REVIEW"
        db.commit()
        db.refresh(item)
        return item

    def approve_image(self, db: Session, item: ImportedItem, image_id: int) -> ImportedItem:
        target = self._find_image(item, image_id)
        if target.selected_variant == "enhanced" and not target.enhanced_path:
            raise ImageReviewError("Selected enhanced variant is unavailable.")

        for image in item.images:
            image.selected_for_publish = image.id == target.id
            if image.id == target.id:
                image.validation_status = "APPROVED"

        db.commit()
        db.refresh(item)
        return item

    def reject_image(self, db: Session, item: ImportedItem, image_id: int) -> ImportedItem:
        target = self._find_image(item, image_id)
        target.validation_status = "REJECTED"
        target.selected_for_publish = False
        target.selected_variant = "original"
        db.commit()
        db.refresh(item)
        return item
