from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import IMAGE_MAX_INPUT_IMAGES
from app.models import ImportedItem, ListingImage
from app.schemas_ai import ImageQualityAnalysis
from app.services.llm_provider import LLMImageInput, LLMProviderError, LLMRequest
from app.services.lm_studio_provider import LMStudioProvider


IMAGE_ANALYSIS_SYSTEM_PROMPT = """
You are a resale listing image quality analyst.
You must preserve factual product condition.
Return JSON only and never include markdown.
Do not invent details that are not visible.
""".strip()


@dataclass(slots=True)
class ImageAnalysisSummary:
    item_id: int
    analyzed: int
    failed: int
    recommended_primary_image_id: int | None


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

    import base64

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _build_user_prompt(item: ImportedItem, image_order: int) -> str:
    title = item.title or ""
    size = item.size or ""
    condition = item.condition or ""
    description = item.description_notes or ""

    return f"""
Analyze this resale product listing photo.

Listing context:
- title: {title}
- size: {size}
- condition: {condition}
- description_notes: {description}
- image_order: {image_order}

Return strict JSON with keys:
- quality_score (0 to 1)
- recommended_as_primary (boolean)
- issues (string list)
- recommended_operations (string list)
- product_condition_visible (string list)
- do_not_modify (string list)
- warnings (string list)
- confidence (0 to 1 or null)

Rules:
- Prioritize factual accuracy over aesthetics.
- Never suggest hiding or removing product damage.
- If visible condition details exist, include them in both product_condition_visible and do_not_modify.
""".strip()


def _store_failure(row: ListingImage, message: str) -> None:
    row.enhancement_status = "ANALYSIS_FAILED"
    row.validation_status = "NEEDS_REVIEW"
    row.ai_analysis = json.dumps(
        {
            "warnings": [message],
            "quality_score": 0.0,
            "recommended_as_primary": False,
            "issues": ["analysis_failed"],
            "recommended_operations": [],
            "product_condition_visible": [],
            "do_not_modify": [],
            "confidence": None,
        }
    )


def analyze_listing_images(
    db: Session,
    item: ImportedItem,
    provider: LMStudioProvider | None = None,
    max_images: int = IMAGE_MAX_INPUT_IMAGES,
) -> ImageAnalysisSummary:
    llm = provider or LMStudioProvider()

    image_rows = (
        db.query(ListingImage)
        .filter(ListingImage.item_id == item.id)
        .order_by(ListingImage.image_order.asc(), ListingImage.id.asc())
        .all()
    )

    image_rows = image_rows[:max_images]

    analyzed = 0
    failed = 0
    candidates: list[tuple[ListingImage, ImageQualityAnalysis]] = []

    for row in image_rows:
        source_path_str = row.processed_path or row.local_original_path
        if not source_path_str:
            _store_failure(row, "No local image path available for analysis.")
            failed += 1
            continue

        source_path = Path(source_path_str)
        if not source_path.exists():
            _store_failure(row, f"Image path does not exist: {source_path}")
            failed += 1
            continue

        try:
            request = LLMRequest(
                system_prompt=IMAGE_ANALYSIS_SYSTEM_PROMPT,
                user_prompt=_build_user_prompt(item, row.image_order),
                images=[LLMImageInput(data_url=_image_to_data_url(source_path))],
                max_tokens=400,
                temperature=0.1,
            )
            raw_json = llm.generate_json(request)
            parsed = ImageQualityAnalysis.model_validate(raw_json)

            row.quality_score = parsed.quality_score
            row.ai_analysis = json.dumps(parsed.model_dump())
            row.enhancement_status = "ANALYZED"
            row.validation_status = "PENDING"
            candidates.append((row, parsed))
            analyzed += 1
        except (LLMProviderError, ValueError) as exc:
            _store_failure(row, f"Qwen image analysis failed: {exc}")
            failed += 1

    for row in image_rows:
        row.is_primary_recommended = False

    recommended_primary: ListingImage | None = None
    recommended_candidates = [
        (row, parsed)
        for row, parsed in candidates
        if parsed.recommended_as_primary
    ]

    if recommended_candidates:
        recommended_primary = max(
            recommended_candidates,
            key=lambda value: value[1].quality_score,
        )[0]
    elif candidates:
        recommended_primary = max(candidates, key=lambda value: value[1].quality_score)[0]

    if recommended_primary is not None:
        recommended_primary.is_primary_recommended = True

    if analyzed > 0 and item.listing_status == "IMPORTED":
        item.listing_status = "AI_ANALYZED"

    db.commit()
    return ImageAnalysisSummary(
        item_id=item.id,
        analyzed=analyzed,
        failed=failed,
        recommended_primary_image_id=recommended_primary.id if recommended_primary else None,
    )
