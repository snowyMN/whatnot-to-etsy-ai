from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.config import (
    IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
    IMAGE_JPEG_QUALITY,
    IMAGE_MAX_INPUT_IMAGES,
    IMAGE_MAX_LONG_SIDE,
    IMAGE_STORAGE_DIR,
)
from app.models import ImportedItem, ListingImage


@dataclass(slots=True)
class ImageSyncSummary:
    item_id: int
    discovered_urls: int
    synced_rows: int
    downloaded: int
    failed: int


def _load_image_urls(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    urls: list[str] = []
    seen: set[str] = set()
    for value in parsed:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        urls.append(normalized)
    return urls


def _safe_extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return suffix
    return ".jpg"


def _item_image_dir(item_id: int) -> Path:
    image_dir = Path(IMAGE_STORAGE_DIR) / f"item_{item_id}"
    image_dir.mkdir(parents=True, exist_ok=True)
    return image_dir


def _download_bytes(url: str) -> bytes:
    response = requests.get(url, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.content


def _normalize_for_processing(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content)) as raw_image:
        image = ImageOps.exif_transpose(raw_image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        elif image.mode == "L":
            image = image.convert("RGB")

        longest_side = max(image.size)
        if longest_side > IMAGE_MAX_LONG_SIDE:
            scale = IMAGE_MAX_LONG_SIDE / float(longest_side)
            target = (
                max(1, int(image.width * scale)),
                max(1, int(image.height * scale)),
            )
            image = image.resize(target, Image.Resampling.LANCZOS)

        return image.copy()


def _serialize_warning(message: str) -> str:
    return json.dumps({"warnings": [message]})


def sync_listing_images_for_item(
    db: Session,
    item: ImportedItem,
    max_images: int = IMAGE_MAX_INPUT_IMAGES,
) -> ImageSyncSummary:
    urls = _load_image_urls(item.image_urls)
    limited_urls = urls[:max_images]

    existing_by_url = {
        image.original_url: image
        for image in db.query(ListingImage).filter(ListingImage.item_id == item.id).all()
        if image.original_url
    }

    image_dir = _item_image_dir(item.id)

    synced_rows = 0
    downloaded = 0
    failed = 0

    for index, url in enumerate(limited_urls):
        row = existing_by_url.get(url)
        if row is None:
            row = ListingImage(
                item_id=item.id,
                original_url=url,
                image_order=index,
                enhancement_status="ORIGINAL",
                validation_status="PENDING",
            )
            db.add(row)

        row.image_order = index

        if row.local_original_path and Path(row.local_original_path).exists() and row.processed_path and Path(row.processed_path).exists():
            synced_rows += 1
            continue

        original_ext = _safe_extension_from_url(url)
        original_path = image_dir / f"original_{index:02d}{original_ext}"
        processed_path = image_dir / f"processed_{index:02d}.jpg"

        try:
            content = _download_bytes(url)
            original_path.write_bytes(content)

            normalized_image = _normalize_for_processing(content)
            normalized_image.save(
                processed_path,
                format="JPEG",
                quality=IMAGE_JPEG_QUALITY,
                optimize=True,
            )

            row.local_original_path = str(original_path)
            row.processed_path = str(processed_path)
            row.enhancement_status = "ORIGINAL"
            row.validation_status = "PENDING"
            row.ai_analysis = None
            downloaded += 1
        except Exception as exc:  # noqa: BLE001
            row.enhancement_status = "DOWNLOAD_FAILED"
            row.validation_status = "NEEDS_REVIEW"
            row.ai_analysis = _serialize_warning(f"Image ingest failed for {url}: {exc}")
            failed += 1

        synced_rows += 1

    db.commit()
    return ImageSyncSummary(
        item_id=item.id,
        discovered_urls=len(urls),
        synced_rows=synced_rows,
        downloaded=downloaded,
        failed=failed,
    )
