from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConfidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: float | None = Field(default=None, ge=0.0, le=1.0)
    by_field: dict[str, float] = Field(default_factory=dict)

    @field_validator("by_field")
    @classmethod
    def validate_field_confidence(cls, value: dict[str, float]) -> dict[str, float]:
        for key, score in value.items():
            if score < 0.0 or score > 1.0:
                raise ValueError(f"Confidence score for '{key}' must be between 0.0 and 1.0")
        return value


class ProductAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    brand: str | None = None
    category: str | None = None
    item_type: str | None = None
    gender: str | None = None
    size: str | None = None

    primary_color: str | None = None
    secondary_colors: list[str] = Field(default_factory=list)
    pattern: str | None = None
    style: list[str] = Field(default_factory=list)

    material: str | None = None
    neckline: str | None = None
    sleeve_type: str | None = None
    fit: str | None = None
    features: list[str] = Field(default_factory=list)

    condition_summary: str | None = None
    visible_defects: list[str] = Field(default_factory=list)

    keywords: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: ConfidenceResult = Field(default_factory=ConfidenceResult)


class ListingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=220)
    description: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    rationale: str | None = None


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: Literal[
        "UNSUPPORTED_CLAIM",
        "CONTRADICTION",
        "MISSING_IMPORTANT_INFO",
        "LOW_CONFIDENCE_CLAIM",
        "FORMATTING_ISSUE",
    ]
    severity: Literal["info", "warning", "error"] = "warning"
    field: str | None = None
    message: str
    suggested_fix: str | None = None


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_valid: bool
    requires_review: bool = True
    issues: list[ValidationIssue] = Field(default_factory=list)


class ImageQualityAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    quality_score: float = Field(ge=0.0, le=1.0)
    recommended_as_primary: bool = False
    issues: list[str] = Field(default_factory=list)
    recommended_operations: list[str] = Field(default_factory=list)
    product_condition_visible: list[str] = Field(default_factory=list)
    do_not_modify: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ImageAnalysisBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    analyzed: int
    failed: int
    recommended_primary_image_id: int | None = None


class ImageValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    passed: bool
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    possible_changes: list[str] = Field(default_factory=list)
    condition_details_preserved: bool = True
    brand_logo_preserved: bool = True
    color_preserved: bool = True
    notes: list[str] = Field(default_factory=list)


class ImageEnhancementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    image_id: int
    enhancement_status: str
    validation_status: str
    processing_path: str
    enhanced_preview_url: str | None = None


class EnhanceImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force_provider: Literal["auto", "deterministic", "comfyui"] = "auto"
    output_width: int = Field(default=1024, ge=256, le=2048)
    output_height: int = Field(default=1024, ge=256, le=2048)


class AnalyzeListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_images: int = Field(default=4, ge=0, le=8)
    force_regenerate: bool = False


class EnhanceListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_images: int = Field(default=4, ge=0, le=8)
    force_regenerate: bool = False


class SaveDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=220)
    description: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)


class ApproveListingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    approved_by: str | None = None


class ItemAIView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    listing_status: str
    analysis: ProductAnalysis | None = None
    draft: ListingDraft | None = None
    validation: ValidationResult | None = None


class ListingEnhancementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    status: str
    analysis_completed: bool
    draft_completed: bool
    requires_review: bool
    recommended_primary_image_id: int | None = None


class ListingImageView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    image_order: int
    original_url: str | None = None
    local_original_path: str | None = None
    processed_path: str | None = None
    enhanced_path: str | None = None
    original_preview_url: str | None = None
    processed_preview_url: str | None = None
    enhanced_preview_url: str | None = None
    quality_score: float | None = None
    enhancement_status: str
    validation_status: str
    ai_validation: ImageValidationResult | None = None
    is_primary_recommended: bool
    is_primary_selected: bool
    selected_for_publish: bool
    selected_variant: str


class ItemDetailView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    source_url: str
    title: str | None = None
    price: str | None = None
    size: str | None = None
    condition: str | None = None
    description_notes: str | None = None
    review_notes: str | None = None
    listing_status: str
    approved_at: str | None = None
    approved_by: str | None = None
    ai: ItemAIView | None = None
    images: list[ListingImageView] = Field(default_factory=list)
