from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import IMAGE_MAX_INPUT_IMAGES
from app.models import ImportedItem, ItemAIRecord, ListingImage
from app.schemas_ai import ListingDraft, ProductAnalysis, ValidationIssue, ValidationResult
from app.services.image_analysis import analyze_listing_images
from app.services.llm_provider import LLMImageInput, LLMProviderError, LLMRequest
from app.services.lm_studio_provider import LMStudioProvider


PRODUCT_ANALYSIS_SYSTEM_PROMPT = """
You are a resale product analyst.
Use only the provided listing text and images.
Return strict JSON only.
Do not guess unsupported facts.
If a field cannot be determined, return null and include it in unknown_fields.
Visible condition details must be preserved and never minimized.
""".strip()

DRAFT_SYSTEM_PROMPT = """
You are a marketplace-neutral resale listing writer.
Use the structured product analysis as the main source of truth, along with the original listing.
Return strict JSON only.
Do not invent facts.
Keep the title clear and concise.
Keep the description factual and easy to review.
""".strip()

VALIDATION_SYSTEM_PROMPT = """
You are a resale listing validator.
Compare the source listing and structured draft.
Return strict JSON only.
Flag unsupported claims, contradictions, and low-confidence facts stated as certain.
Manual review is preferred over silent guessing.
""".strip()


@dataclass(slots=True)
class ListingEnhancementSummary:
    item_id: int
    status: str
    analysis_completed: bool
    draft_completed: bool
    requires_review: bool
    recommended_primary_image_id: int | None


class LocalListingAIService:
    def __init__(self, provider: LMStudioProvider | None = None) -> None:
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

    def _select_image_rows(self, item: ImportedItem, max_images: int) -> list[ListingImage]:
        sorted_rows = sorted(item.images, key=lambda row: (row.image_order, row.id or 0))
        return sorted_rows[:max_images]

    def _image_to_data_url(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif suffix == ".png":
            mime = "image/png"
        elif suffix == ".webp":
            mime = "image/webp"
        else:
            mime = "application/octet-stream"

        import base64

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def _collect_image_inputs(self, item: ImportedItem, max_images: int) -> tuple[list[LLMImageInput], list[dict[str, object]]]:
        images: list[LLMImageInput] = []
        image_summaries: list[dict[str, object]] = []

        for row in self._select_image_rows(item, max_images):
            source_path_str = row.processed_path or row.local_original_path
            if not source_path_str:
                continue

            source_path = Path(source_path_str)
            if not source_path.exists():
                continue

            images.append(LLMImageInput(data_url=self._image_to_data_url(source_path)))

            analysis_json: dict[str, object] | None = None
            if row.ai_analysis:
                try:
                    parsed = json.loads(row.ai_analysis)
                    if isinstance(parsed, dict):
                        analysis_json = parsed
                except json.JSONDecodeError:
                    analysis_json = None

            image_summaries.append(
                {
                    "image_id": row.id,
                    "image_order": row.image_order,
                    "quality_score": row.quality_score,
                    "is_primary_recommended": row.is_primary_recommended,
                    "analysis": analysis_json,
                }
            )

        return images, image_summaries

    def _build_source_payload(self, item: ImportedItem, image_summaries: list[dict[str, object]]) -> dict[str, object]:
        return {
            "source_url": item.source_url,
            "title": item.title,
            "price": item.price,
            "size": item.size,
            "condition": item.condition,
            "description_notes": item.description_notes,
            "review_notes": item.review_notes,
            "image_summaries": image_summaries,
        }

    def analyze_product(
        self,
        item: ImportedItem,
        *,
        max_images: int = IMAGE_MAX_INPUT_IMAGES,
    ) -> tuple[ProductAnalysis, int | None, list[dict[str, object]]]:
        image_summary = analyze_listing_images(
            Session.object_session(item),
            item,
            provider=self.provider,
            max_images=max_images,
        )
        image_inputs, image_summaries = self._collect_image_inputs(item, max_images)
        source_payload = self._build_source_payload(item, image_summaries)

        request = LLMRequest(
            system_prompt=PRODUCT_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=(
                "Analyze this imported resale listing and return strict JSON matching the product analysis schema.\n\n"
                + json.dumps(source_payload, indent=2)
            ),
            images=image_inputs,
            max_tokens=700,
            temperature=0.1,
        )
        raw = self.provider.generate_json(request)
        parsed = ProductAnalysis.model_validate(raw)
        return parsed, image_summary.recommended_primary_image_id, image_summaries

    def generate_listing_draft(
        self,
        item: ImportedItem,
        analysis: ProductAnalysis,
    ) -> ListingDraft:
        source_payload = {
            "title": item.title,
            "price": item.price,
            "size": item.size,
            "condition": item.condition,
            "description_notes": item.description_notes,
            "review_notes": item.review_notes,
            "analysis": analysis.model_dump(),
        }
        request = LLMRequest(
            system_prompt=DRAFT_SYSTEM_PROMPT,
            user_prompt=(
                "Write a marketplace-neutral resale draft and return strict JSON matching the listing draft schema.\n\n"
                + json.dumps(source_payload, indent=2)
            ),
            max_tokens=700,
            temperature=0.2,
        )
        raw = self.provider.generate_json(request)
        return ListingDraft.model_validate(raw)

    def validate_listing(
        self,
        item: ImportedItem,
        analysis: ProductAnalysis,
        draft: ListingDraft,
    ) -> ValidationResult:
        source_title = item.title or ""
        source_description = item.description_notes or ""
        issues: list[ValidationIssue] = []

        if item.review_notes:
            issues.append(
                ValidationIssue(
                    code="MISSING_IMPORTANT_INFO",
                    severity="warning",
                    field="review_notes",
                    message=item.review_notes,
                )
            )

        analysis_type = (analysis.item_type or "").strip().lower()
        if analysis_type and source_title and analysis_type not in source_title.lower() and analysis_type not in source_description.lower():
            issues.append(
                ValidationIssue(
                    code="LOW_CONFIDENCE_CLAIM",
                    severity="warning",
                    field="item_type",
                    message=(
                        f"Generated item_type '{analysis.item_type}' is not explicitly stated in the source listing."
                    ),
                    suggested_fix="Keep item type generic or mark it unknown if uncertain.",
                )
            )

        prompt_payload = {
            "source": {
                "title": item.title,
                "price": item.price,
                "size": item.size,
                "condition": item.condition,
                "description_notes": item.description_notes,
                "review_notes": item.review_notes,
            },
            "analysis": analysis.model_dump(),
            "draft": draft.model_dump(),
            "existing_issues": [issue.model_dump() for issue in issues],
        }
        request = LLMRequest(
            system_prompt=VALIDATION_SYSTEM_PROMPT,
            user_prompt=(
                "Validate this listing draft and return strict JSON matching the validation result schema.\n\n"
                + json.dumps(prompt_payload, indent=2)
            ),
            max_tokens=500,
            temperature=0.0,
        )
        raw = self.provider.generate_json(request)
        parsed = ValidationResult.model_validate(raw)

        if issues:
            parsed = ValidationResult(
                is_valid=parsed.is_valid and not any(issue.severity == "error" for issue in issues),
                requires_review=True,
                issues=[*issues, *parsed.issues],
            )

        return parsed

    def _persist_record(
        self,
        db: Session,
        item: ImportedItem,
        analysis: ProductAnalysis,
        draft: ListingDraft,
        validation: ValidationResult,
        image_summaries: list[dict[str, object]],
    ) -> ItemAIRecord:
        record = self._get_or_create_ai_record(db, item)

        record.ai_title = draft.title
        record.ai_description = draft.description
        record.ai_keywords = json.dumps(draft.keywords)

        record.ai_brand = analysis.brand
        record.ai_category = analysis.category
        record.ai_item_type = analysis.item_type
        record.ai_gender = analysis.gender
        record.ai_size = analysis.size

        record.ai_primary_color = analysis.primary_color
        record.ai_secondary_colors = json.dumps(analysis.secondary_colors)
        record.ai_pattern = analysis.pattern
        record.ai_style = json.dumps(analysis.style)

        record.ai_material = analysis.material
        record.ai_neckline = analysis.neckline
        record.ai_sleeve_type = analysis.sleeve_type
        record.ai_fit = analysis.fit
        record.ai_features = json.dumps(analysis.features)

        record.ai_condition_summary = analysis.condition_summary
        record.ai_visible_defects = json.dumps(analysis.visible_defects)
        record.ai_confidence = json.dumps(analysis.confidence.model_dump())
        record.ai_unknown_fields = json.dumps(analysis.unknown_fields)
        record.ai_warnings = json.dumps(
            {
                "analysis_warnings": analysis.warnings,
                "validation_issues": [issue.model_dump() for issue in validation.issues],
            }
        )
        record.generated_by_model = getattr(self.provider, "model", "local-llm")
        record.generated_at = datetime.utcnow()
        record.image_input_summary = json.dumps(image_summaries)

        item.listing_status = "NEEDS_REVIEW"
        db.commit()
        db.refresh(record)
        return record

    def enhance_item(
        self,
        db: Session,
        item: ImportedItem,
        *,
        max_images: int = IMAGE_MAX_INPUT_IMAGES,
    ) -> ListingEnhancementSummary:
        try:
            analysis, recommended_primary_image_id, image_summaries = self.analyze_product(
                item,
                max_images=max_images,
            )
            item.listing_status = "AI_ANALYZED"

            draft = self.generate_listing_draft(item, analysis)
            item.listing_status = "AI_GENERATED"

            validation = self.validate_listing(item, analysis, draft)
            self._persist_record(db, item, analysis, draft, validation, image_summaries)

            return ListingEnhancementSummary(
                item_id=item.id,
                status=item.listing_status,
                analysis_completed=True,
                draft_completed=True,
                requires_review=validation.requires_review,
                recommended_primary_image_id=recommended_primary_image_id,
            )
        except (LLMProviderError, ValueError) as exc:
            record = self._get_or_create_ai_record(db, item)
            record.ai_warnings = json.dumps(
                {
                    "pipeline_error": str(exc),
                }
            )
            record.generated_by_model = getattr(self.provider, "model", "local-llm")
            record.generated_at = datetime.utcnow()
            item.listing_status = "NEEDS_REVIEW"
            db.commit()
            raise

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
        record.generated_at = datetime.utcnow()
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
        item.approved_at = datetime.utcnow()
        item.approved_by = approved_by
        db.commit()
        db.refresh(item)
        return item
