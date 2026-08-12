from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal
from app.models import ImportedItem
from app.services.image_analysis import analyze_listing_images


def main() -> None:
    db = SessionLocal()
    try:
        item = db.query(ImportedItem).order_by(ImportedItem.id.desc()).first()
        if not item:
            print("No items found. Import at least one item first.")
            return

        result = analyze_listing_images(db, item)
        print(
            {
                "item_id": result.item_id,
                "analyzed": result.analyzed,
                "failed": result.failed,
                "recommended_primary_image_id": result.recommended_primary_image_id,
            }
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
