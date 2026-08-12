from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import DATABASE_URL


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    columns = inspector.get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _ensure_imported_items_columns(engine) -> None:
    inspector = inspect(engine)
    if "imported_items" not in inspector.get_table_names():
        print("Skipping imported_items ALTERs: table does not exist yet.")
        return

    alter_statements: list[str] = []

    if not _column_exists(inspector, "imported_items", "listing_status"):
        alter_statements.append(
            "ALTER TABLE imported_items ADD COLUMN listing_status VARCHAR NOT NULL DEFAULT 'IMPORTED'"
        )

    if not _column_exists(inspector, "imported_items", "approved_at"):
        alter_statements.append("ALTER TABLE imported_items ADD COLUMN approved_at DATETIME")

    if not _column_exists(inspector, "imported_items", "approved_by"):
        alter_statements.append("ALTER TABLE imported_items ADD COLUMN approved_by VARCHAR")

    if not alter_statements:
        print("imported_items already has workflow columns.")
        return

    with engine.begin() as conn:
        for sql in alter_statements:
            conn.execute(text(sql))
        conn.execute(
            text(
                """
                UPDATE imported_items
                SET listing_status = 'IMPORTED'
                WHERE listing_status IS NULL OR TRIM(listing_status) = ''
                """
            )
        )

    print(f"Applied {len(alter_statements)} imported_items ALTER statement(s).")


def _ensure_item_ai_records_table(engine) -> None:
    inspector = inspect(engine)
    if "item_ai_records" in inspector.get_table_names():
        print("item_ai_records already exists.")
        return

    create_table_sql = """
    CREATE TABLE item_ai_records (
        id INTEGER PRIMARY KEY,
        item_id INTEGER NOT NULL UNIQUE,
        ai_title VARCHAR,
        ai_description TEXT,
        ai_keywords TEXT,
        ai_brand VARCHAR,
        ai_category VARCHAR,
        ai_item_type VARCHAR,
        ai_gender VARCHAR,
        ai_size VARCHAR,
        ai_primary_color VARCHAR,
        ai_secondary_colors TEXT,
        ai_pattern VARCHAR,
        ai_style TEXT,
        ai_material VARCHAR,
        ai_neckline VARCHAR,
        ai_sleeve_type VARCHAR,
        ai_fit VARCHAR,
        ai_features TEXT,
        ai_condition_summary TEXT,
        ai_visible_defects TEXT,
        ai_confidence TEXT,
        ai_warnings TEXT,
        ai_unknown_fields TEXT,
        generated_by_model VARCHAR,
        generated_at DATETIME,
        image_input_summary TEXT,
        FOREIGN KEY(item_id) REFERENCES imported_items(id) ON DELETE CASCADE
    )
    """

    with engine.begin() as conn:
        conn.execute(text(create_table_sql))
        conn.execute(text("CREATE INDEX ix_item_ai_records_id ON item_ai_records (id)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_item_ai_records_item_id ON item_ai_records (item_id)"))

    print("Created item_ai_records table and indexes.")


def _ensure_listing_images_table(engine) -> None:
    inspector = inspect(engine)
    if "listing_images" in inspector.get_table_names():
        alter_statements: list[str] = []
        if not _column_exists(inspector, "listing_images", "selected_variant"):
            alter_statements.append(
                "ALTER TABLE listing_images ADD COLUMN selected_variant VARCHAR NOT NULL DEFAULT 'original'"
            )

        if alter_statements:
            with engine.begin() as conn:
                for sql in alter_statements:
                    conn.execute(text(sql))
            print(f"Applied {len(alter_statements)} listing_images ALTER statement(s).")
        else:
            print("listing_images already exists.")
        return

    create_table_sql = """
    CREATE TABLE listing_images (
        id INTEGER PRIMARY KEY,
        item_id INTEGER NOT NULL,
        original_url VARCHAR,
        local_original_path VARCHAR,
        processed_path VARCHAR,
        enhanced_path VARCHAR,
        thumbnail_path VARCHAR,
        image_order INTEGER NOT NULL DEFAULT 0,
        is_primary_recommended BOOLEAN NOT NULL DEFAULT 0,
        is_primary_selected BOOLEAN NOT NULL DEFAULT 0,
        selected_for_publish BOOLEAN NOT NULL DEFAULT 0,
        selected_variant VARCHAR NOT NULL DEFAULT 'original',
        quality_score FLOAT,
        enhancement_status VARCHAR NOT NULL DEFAULT 'ORIGINAL',
        validation_status VARCHAR NOT NULL DEFAULT 'PENDING',
        enhancement_operations TEXT,
        ai_analysis TEXT,
        ai_validation TEXT,
        validation_confidence FLOAT,
        created_at DATETIME,
        updated_at DATETIME,
        FOREIGN KEY(item_id) REFERENCES imported_items(id) ON DELETE CASCADE
    )
    """

    with engine.begin() as conn:
        conn.execute(text(create_table_sql))
        conn.execute(text("CREATE INDEX ix_listing_images_id ON listing_images (id)"))
        conn.execute(text("CREATE INDEX ix_listing_images_item_id ON listing_images (item_id)"))

    print("Created listing_images table and indexes.")


def _backfill_listing_images_from_urls(engine) -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "imported_items" not in table_names or "listing_images" not in table_names:
        print("Skipping listing_images backfill: required tables missing.")
        return

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, image_urls FROM imported_items ORDER BY id ASC")
        ).fetchall()

        inserted_count = 0
        for row in rows:
            item_id = row.id
            image_urls_raw = row.image_urls

            existing_count = conn.execute(
                text("SELECT COUNT(1) FROM listing_images WHERE item_id = :item_id"),
                {"item_id": item_id},
            ).scalar_one()

            if existing_count > 0:
                continue

            if not image_urls_raw:
                continue

            try:
                image_urls = json.loads(image_urls_raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(image_urls, list):
                continue

            seen: set[str] = set()
            for index, url in enumerate(image_urls):
                if not isinstance(url, str):
                    continue
                normalized = url.strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)

                conn.execute(
                    text(
                        """
                        INSERT INTO listing_images (
                            item_id,
                            original_url,
                            image_order,
                            enhancement_status,
                            validation_status
                        ) VALUES (
                            :item_id,
                            :original_url,
                            :image_order,
                            'ORIGINAL',
                            'PENDING'
                        )
                        """
                    ),
                    {
                        "item_id": item_id,
                        "original_url": normalized,
                        "image_order": index,
                    },
                )
                inserted_count += 1

    print(f"Backfilled {inserted_count} listing_images row(s) from imported_items.image_urls.")


def main() -> None:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
        if DATABASE_URL.startswith("sqlite")
        else {},
    )

    _ensure_imported_items_columns(engine)
    _ensure_item_ai_records_table(engine)
    _ensure_listing_images_table(engine)
    _backfill_listing_images_from_urls(engine)
    print("Local DB migration complete.")


if __name__ == "__main__":
    main()
