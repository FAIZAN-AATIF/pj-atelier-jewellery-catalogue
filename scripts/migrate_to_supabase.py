"""One-time migration: existing SQLite catalogue + product JPGs -> Supabase Postgres/Storage.

Run from the project root after setting DATABASE_URL, SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY and SUPABASE_BUCKET in your local environment.
The script is safe to re-run: storage uploads use upsert and database rows
are inserted/updated by their existing IDs.
"""
from __future__ import annotations



import os
import sqlite3
import time
import mimetypes

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.main import Base, Category, Product


# --------------------------------------------------
# PROJECT CONFIGURATION
# --------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

load_dotenv(ROOT / ".env")

SOURCE_DB = ROOT / "pj_catalogue.db"
UPLOADS = ROOT / "uploads"

DATABASE_URL = os.environ["DATABASE_URL"]
DATABASE_URL = DATABASE_URL.replace(
    "postgresql://",
    "postgresql+psycopg://",
    1,
)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BUCKET = os.getenv("SUPABASE_BUCKET", "jewellery_images")

if not SOURCE_DB.is_file():
    raise SystemExit(f"SQLite database not found: {SOURCE_DB}")

if not UPLOADS.is_dir():
    raise SystemExit(f"Uploads directory not found: {UPLOADS}")

if not SERVICE_KEY or not SUPABASE_URL:
    raise SystemExit("Missing Supabase configuration.")

# --------------------------------------------------
# READ ORIGINAL SQLITE DATABASE
# --------------------------------------------------

source = sqlite3.connect(SOURCE_DB)
source.row_factory = sqlite3.Row

categories = source.execute(
    "SELECT * FROM categories ORDER BY id"
).fetchall()

products = source.execute(
    "SELECT * FROM products ORDER BY id"
).fetchall()

if len(products) != 800:
    source.close()
    raise SystemExit(
        f"Expected 800 products, found {len(products)}. "
        "Migration stopped."
    )

if len(categories) != 8:
    source.close()
    raise SystemExit(
        f"Expected 8 categories, found {len(categories)}. "
        "Migration stopped."
    )

print("Source database verified.")
print(f"Categories: {len(categories)}")
print(f"Products: {len(products)}")

# --------------------------------------------------
# SUPABASE CONFIGURATION
# --------------------------------------------------

headers_base = {
    "Authorization": f"Bearer {SERVICE_KEY}",
    "apikey": SERVICE_KEY,
}

public_base = (
    f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
)

Base.metadata.create_all(engine)

# --------------------------------------------------
# IMAGE UPLOAD FUNCTION WITH RETRIES
# --------------------------------------------------

def upload_image(client, image_file, object_path):

    encoded_path = quote(object_path, safe="/")

    content_type, _ = mimetypes.guess_type(
        image_file.name
    )

    if not content_type:
        content_type = "application/octet-stream"

    upload_headers = {
        **headers_base,
        "Content-Type": content_type,
        "x-upsert": "true",
    }

    for attempt in range(1, 6):

        try:
            response = client.post(
                f"{SUPABASE_URL}/storage/v1/object/"
                f"{BUCKET}/{encoded_path}",
                headers=upload_headers,
                content=image_file.read_bytes(),
            )

            if response.status_code in (
                429, 500, 502, 503, 504
            ):
                print(
                    f"Temporary server error: "
                    f"{object_path} "
                    f"(attempt {attempt}/5)"
                )

                if attempt < 5:
                    time.sleep(2 ** attempt)
                    continue

            if response.status_code >= 400:
                print(
                    "SUPABASE STORAGE ERROR:",
                    response.status_code,
                )
                print("DETAIL:", response.text)

                raise SystemExit(
                    f"Upload failed: {object_path}"
                )

            return

        except httpx.TransportError as error:

            print(
                f"Network interruption: {object_path} "
                f"(attempt {attempt}/5): "
                f"{type(error).__name__}"
            )

            if attempt == 5:
                raise SystemExit(
                    f"Upload failed after 5 attempts: "
                    f"{object_path}"
                ) from error

            time.sleep(2 ** attempt)

# --------------------------------------------------
# STEP 1: UPLOAD ALL 800 PRODUCT IMAGES
# --------------------------------------------------

print("\nStarting Supabase image migration...")

try:
    with httpx.Client(
        timeout=httpx.Timeout(
            120.0,
            connect=30.0,
        )
    ) as client:

        for index, row in enumerate(
            products,
            start=1,
        ):

            relative = (
                row["image_path"] or ""
            ).replace("\\", "/")

            if (
                not relative
                or relative.startswith("/")
                or ".." in Path(relative).parts
            ):
                raise SystemExit(
                    f"Unsafe image path for product "
                    f"{row['id']}: {relative!r}"
                )

            image_file = (
                UPLOADS / relative
            ).resolve()

            if (
                not image_file.is_relative_to(
                    UPLOADS.resolve()
                )
                or not image_file.is_file()
            ):
                raise SystemExit(
                    f"Missing image for product "
                    f"{row['id']}: {relative}"
                )

            upload_image(
                client,
                image_file,
                relative,
            )

            if index % 25 == 0:
                print(
                    f"Uploaded {index}/800 images"
                )

except Exception:
    source.close()
    engine.dispose()
    raise

print("\nAll 800 product images uploaded successfully.")

# --------------------------------------------------
# STEP 2: MIGRATE CATEGORIES AND PRODUCTS
# --------------------------------------------------

print("\nStarting PostgreSQL catalogue migration...")

try:

    with Session(engine) as db:

        with db.begin():

            # Migrate categories
            for row in categories:

                obj = db.get(
                    Category,
                    row["id"],
                )

                if obj is None:

                    obj = Category(
                        id=row["id"],
                        name=row["name"],
                        description=(
                            row["description"] or ""
                        ),
                    )

                    db.add(obj)

                else:

                    obj.name = row["name"]

                    obj.description = (
                        row["description"] or ""
                    )

            db.flush()

            # Migrate products
            for index, row in enumerate(
                products,
                start=1,
            ):

                relative = (
                    row["image_path"] or ""
                ).replace("\\", "/")

                encoded_path = quote(
                    relative,
                    safe="/",
                )

                obj = db.get(
                    Product,
                    row["id"],
                )

                created_at = (
                    datetime.fromisoformat(
                        row["created_at"]
                    )
                    if row["created_at"]
                    else None
                )

                updated_at = (
                    datetime.fromisoformat(
                        row["updated_at"]
                    )
                    if row["updated_at"]
                    else None
                )

                values = {
                    "sku": row["sku"],
                    "title": row["title"],
                    "description": (
                        row["description"] or ""
                    ),
                    "category_id": row["category_id"],
                    "image_path": (
                        public_base + encoded_path
                    ),
                    "tags": row["tags"] or "",
                    "status": row["status"],
                    "archived": bool(
                        row["archived"]
                    ),
                    "created_at": created_at,
                    "updated_at": updated_at,
                }

                if obj is None:

                    db.add(
                        Product(
                            id=row["id"],
                            **values,
                        )
                    )

                else:

                    for key, value in values.items():
                        setattr(
                            obj,
                            key,
                            value,
                        )

            db.flush()

            # Advance PostgreSQL ID sequences
            db.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence("
                    "'categories', 'id'), "
                    "COALESCE("
                    "(SELECT MAX(id) FROM categories), 1"
                    "), true)"
                )
            )

            db.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence("
                    "'products', 'id'), "
                    "COALESCE("
                    "(SELECT MAX(id) FROM products), 1"
                    "), true)"
                )
            )

    print("\nPostgreSQL transaction committed successfully.")

finally:

    source.close()
    engine.dispose()

# --------------------------------------------------
# MIGRATION COMPLETE
# --------------------------------------------------

print("\n========================================")
print("       MIGRATION COMPLETED")
print("========================================")
print("Categories:       8")
print("Products:         800")
print("Product images:   800")
print("Storage bucket:   jewellery_images")
print("Database:         Supabase PostgreSQL")
print("========================================")

print(
    "\nNext: Verify the catalogue and images "
    "before deploying to Vercel."
)
