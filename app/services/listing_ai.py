from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.ai.workflow import ListingAIOrchestrator
from app.config import IMAGE_MAX_INPUT_IMAGES
from app.models import ImportedItem, ItemAIRecord, ListingImage
from app.schemas_ai import ListingDraft, MarketingStrategy
from app.services.llm_provider import LLMProvider, LLMProviderError
from app.services.lm_studio_provider import LMStudioProvider


@dataclass(slots=True)
class ListingEnhancementSummary:
    item_id: int
    status: str
    analysis_completed: bool
    draft_completed: bool
    requires_review: bool
    recommended_primary_image_id: int | None


class LocalListingAIService:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or LMStudioProvider()

    def _get_or_create_ai_record(self, db: Session, item: ImportedItem) -> ItemAIRecord:
        if item.ai_record is not None:
            return item.ai_record

        record = ItemAIRecord(item_id=item.id)
        db.add(record)
        db.flush()
        item.ai_record = record
        return record

    def get_existing_ai_record(self, item: ImportedItem) -> ItemAIRecord:
        if item.ai_record is None:
            raise ValueError("No AI draft exists for this item yet.")
        return item.ai_record

    def enhance_item(
        self,
        db: Session,
        item: ImportedItem,
        *,
        max_images: int = IMAGE_MAX_INPUT_IMAGES,
    ) -> ListingEnhancementSummary:
        try:
            summary = ListingAIOrchestrator(provider=self.provider).enhance_item(
                db,
                item,
                max_images=max_images,
            )
            return ListingEnhancementSummary(
                item_id=summary.item_id,
                status=summary.status,
                analysis_completed=summary.analysis_completed,
                draft_completed=summary.draft_completed,
                requires_review=summary.requires_review,
                recommended_primary_image_id=summary.recommended_primary_image_id,
            )
        except (LLMProviderError, ValueError) as exc:
            record = self._get_or_create_ai_record(db, item)
            record.ai_warnings = json.dumps(
                {
                    "pipeline_error": str(exc),
                }
            )
            record.generated_by_model = getattr(self.provider, "model", "local-llm")
            record.generated_at = datetime.now(UTC).replace(tzinfo=None)
            item.listing_status = "NEEDS_REVIEW"
            db.commit()
            raise

    def regenerate_marketing_strategy(
        self,
        db: Session,
        item: ImportedItem,
    ) -> ItemAIRecord:
        return ListingAIOrchestrator(provider=self.provider).regenerate_marketing_strategy(db, item)

    def regenerate_listing_draft(
        self,
        db: Session,
        item: ImportedItem,
    ) -> ItemAIRecord:
        return ListingAIOrchestrator(provider=self.provider).regenerate_listing_draft(db, item)

    def save_marketing_strategy(
        self,
        db: Session,
        item: ImportedItem,
        strategy: MarketingStrategy,
    ) -> ItemAIRecord:
        record = self.get_existing_ai_record(item)
        record.marketing_strategy_json = strategy.model_dump_json()
        record.generated_at = datetime.now(UTC).replace(tzinfo=None)
        item.listing_status = "NEEDS_REVIEW"
        db.commit()
        db.refresh(record)
        return record

    def save_draft(
        self,
        db: Session,
        item: ImportedItem,
        draft: ListingDraft,
    ) -> ItemAIRecord:
        record = self.get_existing_ai_record(item)
        record.ai_title = draft.title
        record.ai_description = draft.description
        record.ai_keywords = json.dumps(draft.keywords)
        record.marketplace_draft_json = json.dumps(
            {
                "title": draft.title,
                "description": draft.description,
                "feature_bullets": [],
                "keywords": draft.keywords,
                "condition_statement": draft.rationale,
                "buyer_notes": [],
            }
        )
        record.generated_at = datetime.now(UTC).replace(tzinfo=None)
        item.listing_status = "NEEDS_REVIEW"
        db.commit()
        db.refresh(record)
        return record

    def approve_item(
        self,
        db: Session,
        item: ImportedItem,
        approved_by: str | None = None,
    ) -> ImportedItem:
        record = self.get_existing_ai_record(item)
        if not record.ai_title or not record.ai_description:
            raise ValueError("AI draft is incomplete and cannot be approved.")

        item.listing_status = "APPROVED"
        item.approved_at = datetime.now(UTC).replace(tzinfo=None)
        item.approved_by = approved_by
        db.commit()
        db.refresh(item)
        return item
