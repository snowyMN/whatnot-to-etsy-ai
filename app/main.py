import json
from typing import Any, cast

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse

from app.db import Base, engine, get_db
from app.models import ImportedItem
from app.schemas_ai import (
    ApproveListingRequest,
    EnhanceListingRequest,
    EnhanceImageRequest,
    ImageAnalysisBatchResult,
    ImageEnhancementResult,
    ImageValidationResult,
    ItemAIView,
    ItemDetailView,
    ListingDraft,
    ListingEnhancementResult,
    ListingImageView,
    ProductAnalysis,
    SaveDraftRequest,
    ValidationResult,
)
from app.services.image_analysis import analyze_listing_images
from app.services.image_enhancement import ImageEnhancementService
from app.services.image_pipeline import sync_listing_images_for_item
from app.services.image_review import ImageReviewError, ImageReviewService
from app.services.image_validation import ImageValidationService
from app.services.listing_ai import LocalListingAIService
from app.services.whatnot_scraper import get_listing_links, parse_listing
from app.services.review_flags import build_review_note

# Create database tables if they do not exist yet
Base.metadata.create_all(bind=engine)

app = FastAPI()

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/data-images", StaticFiles(directory="data/images", check_dir=False), name="data-images")


def _parse_json_text(raw_value: str | None) -> dict | list | None:
    if not raw_value:
        return None

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return None


def _local_path_to_preview_url(path_value: str | None) -> str | None:
    if not path_value:
        return None

    normalized = path_value.replace("\\", "/")
    prefix = "data/images/"
    if normalized.startswith(prefix):
        return f"/data-images/{normalized[len(prefix):]}"

    return None


def _warning_payload(raw_value: str | None) -> dict[str, Any]:
    parsed = _parse_json_text(raw_value)
    if isinstance(parsed, dict):
        return parsed
    return {}


def _build_item_ai_view(item: ImportedItem) -> ItemAIView | None:
    record = item.ai_record
    if record is None:
        return None

    warning_payload = _warning_payload(cast(str | None, record.ai_warnings))

    analysis_payload = {
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
        "warnings": warning_payload.get("analysis_warnings") or [],
        "confidence": _parse_json_text(cast(str | None, record.ai_confidence)) or {"overall": None, "by_field": {}},
    }
    draft_payload = {
        "title": cast(str | None, record.ai_title) or "",
        "description": cast(str | None, record.ai_description) or "",
        "keywords": _parse_json_text(cast(str | None, record.ai_keywords)) or [],
        "rationale": None,
    }
    validation_payload = {
        "is_valid": not any(
            issue.get("severity") == "error"
            for issue in (warning_payload.get("validation_issues") or [])
            if isinstance(issue, dict)
        ),
        "requires_review": True,
        "issues": warning_payload.get("validation_issues") or [],
    }

    return ItemAIView(
        item_id=cast(int, item.id),
        listing_status=cast(str, item.listing_status),
        analysis=ProductAnalysis.model_validate(analysis_payload),
        draft=ListingDraft.model_validate(draft_payload) if cast(str | None, record.ai_title) and cast(str | None, record.ai_description) else None,
        validation=ValidationResult.model_validate(validation_payload),
    )


def _build_item_detail_view(item: ImportedItem) -> ItemDetailView:
    images = [
        ListingImageView(
            id=image.id,
            image_order=image.image_order,
            original_url=image.original_url,
            local_original_path=image.local_original_path,
            processed_path=image.processed_path,
            enhanced_path=image.enhanced_path,
            original_preview_url=_local_path_to_preview_url(image.local_original_path) or image.original_url,
            processed_preview_url=_local_path_to_preview_url(image.processed_path),
            enhanced_preview_url=_local_path_to_preview_url(image.enhanced_path),
            quality_score=image.quality_score,
            enhancement_status=image.enhancement_status,
            validation_status=image.validation_status,
            ai_validation=(
                ImageValidationResult.model_validate(_parse_json_text(image.ai_validation))
                if isinstance(_parse_json_text(image.ai_validation), dict)
                else None
            ),
            is_primary_recommended=image.is_primary_recommended,
            is_primary_selected=image.is_primary_selected,
            selected_for_publish=image.selected_for_publish,
            selected_variant=image.selected_variant,
        )
        for image in sorted(item.images, key=lambda row: (row.image_order, row.id or 0))
    ]

    return ItemDetailView(
        id=cast(int, item.id),
        source_url=cast(str, item.source_url),
        title=cast(str | None, item.title),
        price=cast(str | None, item.price),
        size=cast(str | None, item.size),
        condition=cast(str | None, item.condition),
        description_notes=cast(str | None, item.description_notes),
        review_notes=cast(str | None, item.review_notes),
        listing_status=cast(str, item.listing_status),
        approved_at=cast(Any, item.approved_at).isoformat() if cast(Any, item.approved_at) else None,
        approved_by=cast(str | None, item.approved_by),
        ai=_build_item_ai_view(item),
        images=images,
    )

@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    template = templates.get_template("index.html")
    content = template.render(request=request)
    return HTMLResponse(content=content)

@app.post("/import", response_class=HTMLResponse)
def import_storefront(
    request: Request,
    shop_url: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    links = get_listing_links(shop_url)

    saved_items: list[ImportedItem] = []

    # Keep this small while testing so Selenium does not take forever
    for link in links:
        parsed = parse_listing(link)
        review_note = build_review_note(
            parsed.get("title", ""),
            parsed.get("description_notes", "")
        )

        existing = (
            db.query(ImportedItem)
            .filter(ImportedItem.source_url == parsed["source_url"])
            .first()
        )

        if existing:
            # Update existing row with latest scraped values
            existing.title = parsed.get("title", "")
            existing.price = parsed.get("price", "")
            existing.size = parsed.get("size", "")
            existing.condition = parsed.get("condition", "")
            existing.description_notes = parsed.get("description_notes", "")
            setattr(existing, "image_urls", json.dumps(parsed.get("image_urls", [])))
            setattr(existing, "review_notes", review_note)

            db.commit()
            db.refresh(existing)
            sync_listing_images_for_item(db, existing)
            saved_items.append(existing)
            continue

        item = ImportedItem(
            source_url=parsed["source_url"],
            title=parsed.get("title", ""),
            price=parsed.get("price", ""),
            size=parsed.get("size", ""),
            condition=parsed.get("condition", ""),
            description_notes=parsed.get("description_notes", ""),
            image_urls=json.dumps(parsed.get("image_urls", [])),
            review_notes=review_note,
        )

        db.add(item)
        db.commit()
        db.refresh(item)
        sync_listing_images_for_item(db, item)
        saved_items.append(item)

    item_views = [_build_item_detail_view(item) for item in saved_items]
    template = templates.get_template("items.html")
    content = template.render(request=request, items=item_views)
    return HTMLResponse(content=content)

@app.get("/items", response_class=HTMLResponse)
def list_items(
    request: Request,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    rows = db.query(ImportedItem).order_by(ImportedItem.id.desc()).all()
    items = [_build_item_detail_view(item) for item in rows]

    template = templates.get_template("items.html")
    content = template.render(request=request, items=items)
    return HTMLResponse(content=content)


@app.get("/items/{item_id}", response_model=ItemDetailView)
def get_item_detail(
    item_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return _build_item_detail_view(item)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/items/{item_id}/images/cache")
def cache_item_images(
    item_id: int,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    summary = sync_listing_images_for_item(db, item)
    return {
        "item_id": summary.item_id,
        "discovered_urls": summary.discovered_urls,
        "synced_rows": summary.synced_rows,
        "downloaded": summary.downloaded,
        "failed": summary.failed,
    }


@app.post("/items/{item_id}/images/analyze", response_model=ImageAnalysisBatchResult)
def analyze_item_images(
    item_id: int,
    db: Session = Depends(get_db),
) -> ImageAnalysisBatchResult:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Ensure local image assets exist before Qwen analysis.
    sync_listing_images_for_item(db, item)
    summary = analyze_listing_images(db, item)

    return ImageAnalysisBatchResult(
        item_id=summary.item_id,
        analyzed=summary.analyzed,
        failed=summary.failed,
        recommended_primary_image_id=summary.recommended_primary_image_id,
    )


@app.post("/items/{item_id}/enhance", response_model=ListingEnhancementResult)
def enhance_item_listing(
    item_id: int,
    payload: EnhanceListingRequest | None = None,
    db: Session = Depends(get_db),
) -> ListingEnhancementResult:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    request_payload = payload or EnhanceListingRequest()

    try:
        sync_listing_images_for_item(db, item, max_images=request_payload.max_images)
        summary = LocalListingAIService().enhance_item(
            db,
            item,
            max_images=request_payload.max_images,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Local AI enhancement failed: {exc}") from exc

    return ListingEnhancementResult(
        item_id=summary.item_id,
        status=summary.status,
        analysis_completed=summary.analysis_completed,
        draft_completed=summary.draft_completed,
        requires_review=summary.requires_review,
        recommended_primary_image_id=summary.recommended_primary_image_id,
    )


@app.put("/items/{item_id}/draft", response_model=ItemDetailView)
def save_item_draft(
    item_id: int,
    payload: SaveDraftRequest,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    try:
        LocalListingAIService().save_draft(
            db,
            item,
            ListingDraft(
                title=payload.title,
                description=payload.description,
                keywords=payload.keywords,
                rationale=None,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.refresh(item)
    return _build_item_detail_view(item)


@app.post("/items/{item_id}/approve", response_model=ItemDetailView)
def approve_item_listing(
    item_id: int,
    payload: ApproveListingRequest | None = None,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    request_payload = payload or ApproveListingRequest()

    try:
        LocalListingAIService().approve_item(
            db,
            item,
            approved_by=request_payload.approved_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.refresh(item)
    return _build_item_detail_view(item)


def _apply_image_review_action(
    item_id: int,
    image_id: int,
    db: Session,
    action_name: str,
) -> ItemDetailView:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    service = ImageReviewService()
    try:
        if action_name == "select-primary":
            service.select_primary(db, item, image_id)
        elif action_name == "use-original":
            service.choose_original(db, item, image_id)
        elif action_name == "use-enhanced":
            service.choose_enhanced(db, item, image_id)
        elif action_name == "approve-image":
            service.approve_image(db, item, image_id)
        elif action_name == "reject-image":
            service.reject_image(db, item, image_id)
        else:
            raise HTTPException(status_code=400, detail="Unknown image action")
    except ImageReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.refresh(item)
    return _build_item_detail_view(item)


@app.post("/items/{item_id}/images/{image_id}/select-primary", response_model=ItemDetailView)
def select_primary_image(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    return _apply_image_review_action(item_id, image_id, db, "select-primary")


@app.post("/items/{item_id}/images/{image_id}/use-original", response_model=ItemDetailView)
def use_original_image(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    return _apply_image_review_action(item_id, image_id, db, "use-original")


@app.post("/items/{item_id}/images/{image_id}/use-enhanced", response_model=ItemDetailView)
def use_enhanced_image(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    return _apply_image_review_action(item_id, image_id, db, "use-enhanced")


@app.post("/items/{item_id}/images/{image_id}/approve", response_model=ItemDetailView)
def approve_image_asset(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    return _apply_image_review_action(item_id, image_id, db, "approve-image")


@app.post("/items/{item_id}/images/{image_id}/reject", response_model=ItemDetailView)
def reject_image_asset(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    return _apply_image_review_action(item_id, image_id, db, "reject-image")


@app.post("/items/{item_id}/images/{image_id}/enhance", response_model=ImageEnhancementResult)
def enhance_image_asset(
    item_id: int,
    image_id: int,
    payload: EnhanceImageRequest | None = None,
    db: Session = Depends(get_db),
) -> ImageEnhancementResult:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    image = next((row for row in item.images if row.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")

    request_payload = payload or EnhanceImageRequest()
    try:
        result = ImageEnhancementService().enhance_image(
            db,
            item,
            image,
            force_provider=request_payload.force_provider,
            output_width=request_payload.output_width,
            output_height=request_payload.output_height,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Image enhancement failed: {exc}") from exc

    return ImageEnhancementResult(
        item_id=result.item_id,
        image_id=result.image_id,
        enhancement_status=result.enhancement_status,
        validation_status=result.validation_status,
        processing_path=result.processing_path,
        enhanced_preview_url=_local_path_to_preview_url(result.enhanced_path),
    )


@app.post("/items/{item_id}/images/{image_id}/validate", response_model=ItemDetailView)
def validate_image_asset(
    item_id: int,
    image_id: int,
    db: Session = Depends(get_db),
) -> ItemDetailView:
    item = db.query(ImportedItem).filter(ImportedItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    image = next((row for row in item.images if row.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        validation_service = ImageValidationService()
        result = validation_service.validate_image_pair(image)
        validation_service.persist_validation_result(image, result)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Image validation failed: {exc}") from exc

    db.refresh(item)
    return _build_item_detail_view(item)
