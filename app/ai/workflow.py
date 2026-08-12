from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, cast

from sqlalchemy.orm import Session

from app.ai.prompt_registry import (
    LISTING_VALIDATOR_PROMPT,
    LISTING_WRITER_PROMPT,
    MARKETING_STRATEGY_PROMPT,
    PRODUCT_ANALYSIS_PROMPT,
    PromptDefinition,
    render_prompt,
)
from app.config import (
    IMAGE_MAX_INPUT_IMAGES,
    LISTING_VALIDATOR_MODEL,
    LISTING_WRITER_MODEL,
    MARKETING_MODEL,
    PRODUCT_ANALYSIS_MODEL,
)
from app.models import AIExecution, ImportedItem, ItemAIRecord, ListingImage
from app.schemas_ai import (
    ListingDraft,
    ListingValidationResult,
    MarketplaceNeutralListingDraft,
    MarketingStrategy,
    ProductAnalysis,
    ValidationIssue,
    ValidationResult,
    WorkflowStepMetadata,
)
from app.services.image_analysis import analyze_listing_images
from app.services.llm_provider import LLMImageInput, LLMProvider, LLMProviderError, LLMRequest
from app.services.lm_studio_provider import LMStudioProvider


@dataclass(slots=True)
class ListingEnhancementSummary:
    item_id: int
    status: str
    analysis_completed: bool
    draft_completed: bool
    requires_review: bool
    recommended_primary_image_id: int | None


@dataclass(slots=True)
class ProductAnalysisResult:
    analysis: ProductAnalysis
    step: WorkflowStepMetadata
    recommended_primary_image_id: int | None
    image_summaries: list[dict[str, object]]


@dataclass(slots=True)
class AgentResult:
    output: Any
    step: WorkflowStepMetadata
    input_summary: dict[str, Any]


def _provider_for_model(model_name: str) -> LLMProvider:
    return LMStudioProvider(model=model_name)


def _image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    else:
        mime = "application/octet-stream"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _parse_json_text(raw_value: str | None) -> dict[str, Any] | list[Any] | None:
    if not raw_value:
        return None

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _serialize_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def _build_source_payload(item: ImportedItem, image_summaries: list[dict[str, object]]) -> dict[str, object]:
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


class StructuredWorkflowAgent:
    def __init__(
        self,
        *,
        prompt: PromptDefinition,
        model_name: str,
        provider: LLMProvider | None = None,
    ) -> None:
        self.prompt = prompt
        self.model_name = model_name
        self.provider = provider or _provider_for_model(model_name)

    def _run_structured(
        self,
        *,
        user_payload: dict[str, Any],
        response_model: type,
        images: list[LLMImageInput] | None = None,
        max_tokens: int,
        temperature: float,
    ) -> AgentResult:
        started = perf_counter()
        request = LLMRequest(
            system_prompt=render_prompt(self.prompt),
            user_prompt=json.dumps(user_payload, indent=2),
            images=images or [],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        raw = self.provider.generate_json(request)
        parsed = response_model.model_validate(raw)
        duration_ms = int((perf_counter() - started) * 1000)
        return AgentResult(
            output=parsed,
            step=WorkflowStepMetadata(
                task_type=self.prompt.task_type,
                model_name=self.model_name,
                prompt_name=self.prompt.name,
                prompt_version=self.prompt.version,
                success=True,
                duration_ms=duration_ms,
            ),
            input_summary=user_payload,
        )


class ProductAnalysisAgent(StructuredWorkflowAgent):
    def __init__(self, provider: LLMProvider | None = None) -> None:
        super().__init__(
            prompt=PRODUCT_ANALYSIS_PROMPT,
            model_name=PRODUCT_ANALYSIS_MODEL,
            provider=provider,
        )

    @staticmethod
    def _select_image_rows(item: ImportedItem, max_images: int) -> list[ListingImage]:
        sorted_rows = sorted(item.images, key=lambda row: (row.image_order, row.id or 0))
        return sorted_rows[:max_images]

    def _collect_image_inputs(
        self,
        item: ImportedItem,
        max_images: int,
    ) -> tuple[list[LLMImageInput], list[dict[str, object]]]:
        images: list[LLMImageInput] = []
        image_summaries: list[dict[str, object]] = []

        for row in self._select_image_rows(item, max_images):
            source_path_str = cast(str | None, row.processed_path) or cast(str | None, row.local_original_path)
            if not source_path_str:
                continue

            source_path = Path(source_path_str)
            if not source_path.exists():
                continue

            images.append(LLMImageInput(data_url=_image_to_data_url(source_path)))
            analysis_json = _parse_json_text(cast(str | None, row.ai_analysis))

            image_summaries.append(
                {
                    "image_id": row.id,
                    "image_order": row.image_order,
                    "quality_score": row.quality_score,
                    "is_primary_recommended": row.is_primary_recommended,
                    "analysis": analysis_json if isinstance(analysis_json, dict) else None,
                }
            )

        return images, image_summaries

    def analyze(
        self,
        db: Session,
        item: ImportedItem,
        *,
        max_images: int = IMAGE_MAX_INPUT_IMAGES,
    ) -> ProductAnalysisResult:
        image_summary = analyze_listing_images(
            db,
            item,
            provider=cast(Any, self.provider),
            max_images=max_images,
        )
        image_inputs, image_summaries = self._collect_image_inputs(item, max_images)
        payload = {
            "source_listing": _build_source_payload(item, image_summaries),
            "instruction": "Return ProductAnalysis JSON only.",
        }
        result = self._run_structured(
            user_payload=payload,
            response_model=ProductAnalysis,
            images=image_inputs,
            max_tokens=900,
            temperature=0.1,
        )
        return ProductAnalysisResult(
            analysis=cast(ProductAnalysis, result.output),
            step=result.step,
            recommended_primary_image_id=image_summary.recommended_primary_image_id,
            image_summaries=image_summaries,
        )


class MarketingStrategyAgent(StructuredWorkflowAgent):
    def __init__(self, provider: LLMProvider | None = None) -> None:
        super().__init__(
            prompt=MARKETING_STRATEGY_PROMPT,
            model_name=MARKETING_MODEL,
            provider=provider,
        )

    def generate(self, item: ImportedItem, analysis: ProductAnalysis) -> AgentResult:
        payload = {
            "source_listing": {
                "title": item.title,
                "price": item.price,
                "size": item.size,
                "condition": item.condition,
                "description_notes": item.description_notes,
            },
            "verified_product_analysis": analysis.model_dump(),
            "instruction": "Use only verified facts to produce MarketingStrategy JSON.",
        }
        return self._run_structured(
            user_payload=payload,
            response_model=MarketingStrategy,
            max_tokens=800,
            temperature=0.2,
        )


class ListingWriterAgent(StructuredWorkflowAgent):
    def __init__(self, provider: LLMProvider | None = None) -> None:
        super().__init__(
            prompt=LISTING_WRITER_PROMPT,
            model_name=LISTING_WRITER_MODEL,
            provider=provider,
        )

    def generate(
        self,
        item: ImportedItem,
        analysis: ProductAnalysis,
        strategy: MarketingStrategy,
    ) -> AgentResult:
        payload = {
            "source_listing": {
                "title": item.title,
                "price": item.price,
                "size": item.size,
                "condition": item.condition,
                "description_notes": item.description_notes,
                "review_notes": item.review_notes,
            },
            "verified_product_analysis": analysis.model_dump(),
            "marketing_strategy": strategy.model_dump(),
            "instruction": "Return MarketplaceNeutralListingDraft JSON only.",
        }
        return self._run_structured(
            user_payload=payload,
            response_model=MarketplaceNeutralListingDraft,
            max_tokens=900,
            temperature=0.2,
        )


class ListingValidatorAgent(StructuredWorkflowAgent):
    def __init__(self, provider: LLMProvider | None = None) -> None:
        super().__init__(
            prompt=LISTING_VALIDATOR_PROMPT,
            model_name=LISTING_VALIDATOR_MODEL,
            provider=provider,
        )

    def validate(
        self,
        item: ImportedItem,
        analysis: ProductAnalysis,
        strategy: MarketingStrategy,
        draft: MarketplaceNeutralListingDraft,
    ) -> AgentResult:
        unsupported_claims: list[str] = []
        warnings: list[str] = []
        recommended_changes: list[str] = []
        issues: list[ValidationIssue] = []
        review_notes = cast(str | None, item.review_notes)

        if review_notes:
            warnings.append(review_notes)
            issues.append(
                ValidationIssue(
                    code="MISSING_IMPORTANT_INFO",
                    severity="warning",
                    field="review_notes",
                    message=review_notes,
                )
            )

        analysis_type = (analysis.item_type or "").strip().lower()
        source_title = (item.title or "").lower()
        source_description = (item.description_notes or "").lower()
        if analysis_type and analysis_type not in source_title and analysis_type not in source_description:
            recommended_changes.append("Keep the item type generic if the source listing does not support the current wording.")
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

        payload = {
            "source_listing": {
                "title": item.title,
                "price": item.price,
                "size": item.size,
                "condition": item.condition,
                "description_notes": item.description_notes,
                "review_notes": item.review_notes,
            },
            "verified_product_analysis": analysis.model_dump(),
            "marketing_strategy": strategy.model_dump(),
            "listing_draft": draft.model_dump(),
            "precomputed_checks": {
                "issues": [issue.model_dump() for issue in issues],
                "warnings": warnings,
                "recommended_changes": recommended_changes,
                "unsupported_claims": unsupported_claims,
            },
            "instruction": "Return ListingValidationResult JSON only.",
        }
        result = self._run_structured(
            user_payload=payload,
            response_model=ListingValidationResult,
            max_tokens=700,
            temperature=0.0,
        )
        parsed = cast(ListingValidationResult, result.output)
        merged = ListingValidationResult(
            passed=parsed.passed and not any(issue.severity == "error" for issue in issues),
            issues=[*issues, *parsed.issues],
            unsupported_claims=[*unsupported_claims, *parsed.unsupported_claims],
            warnings=[*warnings, *parsed.warnings],
            recommended_changes=[*recommended_changes, *parsed.recommended_changes],
        )
        return AgentResult(output=merged, step=result.step, input_summary=result.input_summary)


class ListingAIOrchestrator:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.product_analysis_agent = ProductAnalysisAgent(provider=provider)
        self.marketing_strategy_agent = MarketingStrategyAgent(provider=provider)
        self.listing_writer_agent = ListingWriterAgent(provider=provider)
        self.listing_validator_agent = ListingValidatorAgent(provider=provider)

    @staticmethod
    def _get_or_create_ai_record(db: Session, item: ImportedItem) -> ItemAIRecord:
        if item.ai_record is not None:
            return item.ai_record

        record = ItemAIRecord(item_id=item.id)
        db.add(record)
        db.flush()
        item.ai_record = record
        return record

    @staticmethod
    def _persist_execution(
        db: Session,
        *,
        item_id: int,
        step: WorkflowStepMetadata,
        input_summary: dict[str, Any],
        output_payload: Any,
    ) -> None:
        completed_at = datetime.now(UTC).replace(tzinfo=None)
        started_at = completed_at
        if step.duration_ms is not None:
            started_at = completed_at.fromtimestamp(
                completed_at.timestamp() - (step.duration_ms / 1000)
            )

        db.add(
            AIExecution(
                item_id=item_id,
                task_type=step.task_type,
                model_name=step.model_name,
                prompt_name=step.prompt_name,
                prompt_version=step.prompt_version,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=step.duration_ms,
                success=step.success,
                error=step.error,
                input_summary=json.dumps(input_summary),
                output_json=json.dumps(_serialize_model(output_payload)),
            )
        )

    @staticmethod
    def _build_listing_draft_view(draft: MarketplaceNeutralListingDraft) -> ListingDraft:
        return ListingDraft(
            title=draft.title,
            description=draft.description,
            keywords=draft.keywords,
            rationale=draft.condition_statement,
        )

    @staticmethod
    def _load_existing_analysis(item: ImportedItem) -> ProductAnalysis:
        record = item.ai_record
        if record is None:
            raise ValueError("Product analysis does not exist yet. Run the full AI workflow first.")

        warning_payload = _parse_json_text(cast(str | None, record.ai_warnings))
        analysis_warnings = warning_payload.get("analysis_warnings", []) if isinstance(warning_payload, dict) else []

        return ProductAnalysis.model_validate(
            {
                "brand": cast(str | None, record.ai_brand),
                "category": cast(str | None, record.ai_category),
                "item_type": cast(str | None, record.ai_item_type),
                "gender": cast(str | None, record.ai_gender),
                "size": cast(str | None, record.ai_size),
                "primary_color": cast(str | None, record.ai_primary_color),
                "secondary_colors": _parse_json_text(cast(str | None, record.ai_secondary_colors)) or [],
                "pattern": cast(str | None, record.ai_pattern),
                "style": _parse_json_text(cast(str | None, record.ai_style)) or [],
                "material": cast(str | None, record.ai_material),
                "neckline": cast(str | None, record.ai_neckline),
                "sleeve_type": cast(str | None, record.ai_sleeve_type),
                "fit": cast(str | None, record.ai_fit),
                "features": _parse_json_text(cast(str | None, record.ai_features)) or [],
                "condition_summary": cast(str | None, record.ai_condition_summary),
                "visible_defects": _parse_json_text(cast(str | None, record.ai_visible_defects)) or [],
                "keywords": _parse_json_text(cast(str | None, record.ai_keywords)) or [],
                "unknown_fields": _parse_json_text(cast(str | None, record.ai_unknown_fields)) or [],
                "warnings": analysis_warnings,
                "confidence": _parse_json_text(cast(str | None, record.ai_confidence)) or {"overall": None, "by_field": {}},
            }
        )

    @staticmethod
    def _load_existing_strategy(item: ImportedItem) -> MarketingStrategy:
        record = item.ai_record
        if record is None:
            raise ValueError("Marketing strategy does not exist yet. Run the full AI workflow first.")

        payload = _parse_json_text(cast(str | None, record.marketing_strategy_json))
        if not isinstance(payload, dict):
            raise ValueError("Marketing strategy is missing. Generate it before regenerating the listing draft.")
        return MarketingStrategy.model_validate(payload)

    @staticmethod
    def _load_image_summaries(item: ImportedItem) -> list[dict[str, object]]:
        record = item.ai_record
        if record is None:
            return []

        payload = _parse_json_text(cast(str | None, record.image_input_summary))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []

    @staticmethod
    def _load_workflow_steps(item: ImportedItem) -> list[WorkflowStepMetadata]:
        record = item.ai_record
        if record is None:
            return []

        payload = _parse_json_text(cast(str | None, record.workflow_steps_json))
        if not isinstance(payload, list):
            return []
        return [WorkflowStepMetadata.model_validate(step) for step in payload if isinstance(step, dict)]

    def _persist_record(
        self,
        db: Session,
        item: ImportedItem,
        analysis: ProductAnalysis,
        strategy: MarketingStrategy,
        draft: MarketplaceNeutralListingDraft,
        validation: ListingValidationResult,
        image_summaries: list[dict[str, object]],
        workflow_steps: list[WorkflowStepMetadata],
    ) -> ItemAIRecord:
        record = self._get_or_create_ai_record(db, item)
        listing_draft = self._build_listing_draft_view(draft)

        setattr(record, "ai_title", listing_draft.title)
        setattr(record, "ai_description", listing_draft.description)
        setattr(record, "ai_keywords", json.dumps(listing_draft.keywords))

        setattr(record, "ai_brand", analysis.brand)
        setattr(record, "ai_category", analysis.category)
        setattr(record, "ai_item_type", analysis.item_type)
        setattr(record, "ai_gender", analysis.gender)
        setattr(record, "ai_size", analysis.size)

        setattr(record, "ai_primary_color", analysis.primary_color)
        setattr(record, "ai_secondary_colors", json.dumps(analysis.secondary_colors))
        setattr(record, "ai_pattern", analysis.pattern)
        setattr(record, "ai_style", json.dumps(analysis.style))

        setattr(record, "ai_material", analysis.material)
        setattr(record, "ai_neckline", analysis.neckline)
        setattr(record, "ai_sleeve_type", analysis.sleeve_type)
        setattr(record, "ai_fit", analysis.fit)
        setattr(record, "ai_features", json.dumps(analysis.features))

        setattr(record, "ai_condition_summary", analysis.condition_summary)
        setattr(record, "ai_visible_defects", json.dumps(analysis.visible_defects))
        setattr(record, "ai_confidence", json.dumps(analysis.confidence.model_dump()))
        setattr(record, "ai_unknown_fields", json.dumps(analysis.unknown_fields))
        setattr(record, "ai_warnings", json.dumps(
            {
                "analysis_warnings": analysis.warnings,
                "validation_issues": [issue.model_dump() for issue in validation.issues],
            }
        ))
        setattr(record, "generated_by_model", workflow_steps[-1].model_name if workflow_steps else None)
        setattr(record, "generated_at", datetime.now(UTC).replace(tzinfo=None))
        setattr(record, "image_input_summary", json.dumps(image_summaries))
        setattr(record, "marketing_strategy_json", json.dumps(strategy.model_dump()))
        setattr(record, "marketplace_draft_json", json.dumps(draft.model_dump()))
        setattr(record, "listing_validation_json", json.dumps(validation.model_dump()))
        setattr(record, "workflow_steps_json", json.dumps([step.model_dump() for step in workflow_steps]))

        setattr(item, "listing_status", "NEEDS_REVIEW")
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
        workflow_steps: list[WorkflowStepMetadata] = []

        analysis_result = self.product_analysis_agent.analyze(db, item, max_images=max_images)
        workflow_steps.append(analysis_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=analysis_result.step,
            input_summary={"max_images": max_images, "source_title": item.title or ""},
            output_payload=analysis_result.analysis,
        )
        setattr(item, "listing_status", "AI_ANALYZED")

        marketing_result = self.marketing_strategy_agent.generate(item, analysis_result.analysis)
        workflow_steps.append(marketing_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=marketing_result.step,
            input_summary=marketing_result.input_summary,
            output_payload=marketing_result.output,
        )

        draft_result = self.listing_writer_agent.generate(
            item,
            analysis_result.analysis,
            cast(MarketingStrategy, marketing_result.output),
        )
        workflow_steps.append(draft_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=draft_result.step,
            input_summary=draft_result.input_summary,
            output_payload=draft_result.output,
        )
        setattr(item, "listing_status", "AI_GENERATED")

        validation_result = self.listing_validator_agent.validate(
            item,
            analysis_result.analysis,
            cast(MarketingStrategy, marketing_result.output),
            cast(MarketplaceNeutralListingDraft, draft_result.output),
        )
        workflow_steps.append(validation_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=validation_result.step,
            input_summary=validation_result.input_summary,
            output_payload=validation_result.output,
        )

        self._persist_record(
            db,
            item,
            analysis_result.analysis,
            cast(MarketingStrategy, marketing_result.output),
            cast(MarketplaceNeutralListingDraft, draft_result.output),
            cast(ListingValidationResult, validation_result.output),
            analysis_result.image_summaries,
            workflow_steps,
        )

        return ListingEnhancementSummary(
            item_id=cast(int, item.id),
            status=cast(str, item.listing_status),
            analysis_completed=True,
            draft_completed=True,
            requires_review=not cast(ListingValidationResult, validation_result.output).passed,
            recommended_primary_image_id=analysis_result.recommended_primary_image_id,
        )

    def regenerate_marketing_strategy(self, db: Session, item: ImportedItem) -> ItemAIRecord:
        analysis = self._load_existing_analysis(item)
        workflow_steps = self._load_workflow_steps(item)
        image_summaries = self._load_image_summaries(item)

        marketing_result = self.marketing_strategy_agent.generate(item, analysis)
        workflow_steps.append(marketing_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=marketing_result.step,
            input_summary=marketing_result.input_summary,
            output_payload=marketing_result.output,
        )

        draft_result = self.listing_writer_agent.generate(
            item,
            analysis,
            cast(MarketingStrategy, marketing_result.output),
        )
        workflow_steps.append(draft_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=draft_result.step,
            input_summary=draft_result.input_summary,
            output_payload=draft_result.output,
        )

        validation_result = self.listing_validator_agent.validate(
            item,
            analysis,
            cast(MarketingStrategy, marketing_result.output),
            cast(MarketplaceNeutralListingDraft, draft_result.output),
        )
        workflow_steps.append(validation_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=validation_result.step,
            input_summary=validation_result.input_summary,
            output_payload=validation_result.output,
        )

        return self._persist_record(
            db,
            item,
            analysis,
            cast(MarketingStrategy, marketing_result.output),
            cast(MarketplaceNeutralListingDraft, draft_result.output),
            cast(ListingValidationResult, validation_result.output),
            image_summaries,
            workflow_steps,
        )

    def regenerate_listing_draft(self, db: Session, item: ImportedItem) -> ItemAIRecord:
        analysis = self._load_existing_analysis(item)
        strategy = self._load_existing_strategy(item)
        workflow_steps = self._load_workflow_steps(item)
        image_summaries = self._load_image_summaries(item)

        draft_result = self.listing_writer_agent.generate(item, analysis, strategy)
        workflow_steps.append(draft_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=draft_result.step,
            input_summary=draft_result.input_summary,
            output_payload=draft_result.output,
        )

        validation_result = self.listing_validator_agent.validate(
            item,
            analysis,
            strategy,
            cast(MarketplaceNeutralListingDraft, draft_result.output),
        )
        workflow_steps.append(validation_result.step)
        self._persist_execution(
            db,
            item_id=cast(int, item.id),
            step=validation_result.step,
            input_summary=validation_result.input_summary,
            output_payload=validation_result.output,
        )

        return self._persist_record(
            db,
            item,
            analysis,
            strategy,
            cast(MarketplaceNeutralListingDraft, draft_result.output),
            cast(ListingValidationResult, validation_result.output),
            image_summaries,
            workflow_steps,
        )


def build_legacy_validation_result(validation: ListingValidationResult) -> ValidationResult:
    return ValidationResult(
        is_valid=validation.passed,
        requires_review=not validation.passed or bool(validation.issues or validation.warnings),
        issues=validation.issues,
    )