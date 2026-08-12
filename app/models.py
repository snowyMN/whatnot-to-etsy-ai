from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.db import Base

class ImportedItem(Base):
    __tablename__ = "imported_items"

    id = Column(Integer, primary_key=True, index=True)
    source_url = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=True)
    price = Column(String, nullable=True)
    size = Column(String, nullable=True)
    condition = Column(String, nullable=True)
    description_notes = Column(Text, nullable=True)
    image_urls = Column(Text, nullable=True)
    listing_status = Column(String, nullable=False, default="IMPORTED")
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String, nullable=True)

    etsy_title = Column(String, nullable=True)
    etsy_description = Column(Text, nullable=True)
    etsy_tags = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)

    ai_record = relationship(
        "ItemAIRecord",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )

    images = relationship(
        "ListingImage",
        back_populates="item",
        cascade="all, delete-orphan",
    )


class ItemAIRecord(Base):
    __tablename__ = "item_ai_records"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(
        Integer,
        ForeignKey("imported_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    ai_title = Column(String, nullable=True)
    ai_description = Column(Text, nullable=True)
    ai_keywords = Column(Text, nullable=True)

    ai_brand = Column(String, nullable=True)
    ai_category = Column(String, nullable=True)
    ai_item_type = Column(String, nullable=True)
    ai_gender = Column(String, nullable=True)
    ai_size = Column(String, nullable=True)

    ai_primary_color = Column(String, nullable=True)
    ai_secondary_colors = Column(Text, nullable=True)
    ai_pattern = Column(String, nullable=True)
    ai_style = Column(Text, nullable=True)

    ai_material = Column(String, nullable=True)
    ai_neckline = Column(String, nullable=True)
    ai_sleeve_type = Column(String, nullable=True)
    ai_fit = Column(String, nullable=True)
    ai_features = Column(Text, nullable=True)

    ai_condition_summary = Column(Text, nullable=True)
    ai_visible_defects = Column(Text, nullable=True)

    ai_confidence = Column(Text, nullable=True)
    ai_warnings = Column(Text, nullable=True)
    ai_unknown_fields = Column(Text, nullable=True)

    generated_by_model = Column(String, nullable=True)
    generated_at = Column(DateTime, nullable=True)
    image_input_summary = Column(Text, nullable=True)
    marketing_strategy_json = Column(Text, nullable=True)
    marketplace_draft_json = Column(Text, nullable=True)
    listing_validation_json = Column(Text, nullable=True)
    workflow_steps_json = Column(Text, nullable=True)

    item = relationship("ImportedItem", back_populates="ai_record")


class AIExecution(Base):
    __tablename__ = "ai_executions"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(
        Integer,
        ForeignKey("imported_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type = Column(String, nullable=False)
    model_name = Column(String, nullable=True)
    prompt_name = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    error = Column(Text, nullable=True)
    input_summary = Column(Text, nullable=True)
    output_json = Column(Text, nullable=True)

    item = relationship("ImportedItem")


class ListingImage(Base):
    __tablename__ = "listing_images"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(
        Integer,
        ForeignKey("imported_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    original_url = Column(String, nullable=True)
    local_original_path = Column(String, nullable=True)
    processed_path = Column(String, nullable=True)
    enhanced_path = Column(String, nullable=True)
    thumbnail_path = Column(String, nullable=True)

    image_order = Column(Integer, nullable=False, default=0)
    is_primary_recommended = Column(Boolean, nullable=False, default=False)
    is_primary_selected = Column(Boolean, nullable=False, default=False)
    selected_for_publish = Column(Boolean, nullable=False, default=False)
    selected_variant = Column(String, nullable=False, default="original")

    quality_score = Column(Float, nullable=True)
    enhancement_status = Column(String, nullable=False, default="ORIGINAL")
    validation_status = Column(String, nullable=False, default="PENDING")
    enhancement_operations = Column(Text, nullable=True)
    ai_analysis = Column(Text, nullable=True)
    ai_validation = Column(Text, nullable=True)
    validation_confidence = Column(Float, nullable=True)

    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    item = relationship("ImportedItem", back_populates="images")
