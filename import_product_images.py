"""Map product images to PJ catalogue products using exact SKUs.

Run from the project root:
  python import_product_images.py --export-template product_image_manifest.csv
  # Fill image_file for the rows you want to update.
  python import_product_images.py --manifest product_image_manifest.csv --images-dir image_batches
  python import_product_images.py --manifest product_image_manifest.csv --images-dir image_batches --apply

Preview is the default. Database changes happen only with --apply.
"""
from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.main import SessionLocal, Product, Category

ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
CATEGORY_FOLDERS = {
    "rings": "rings", "necklaces": "necklaces", "earrings": "earrings",
    "bracelets": "bracelets", "bangles": "bangles", "chains": "chains",
    "pendants": "pendants", "anklets": "anklets",
}


def export_template(path: Path) -> None:
    with SessionLocal() as db, path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["sku", "title", "category", "current_image_path", "image_file"])
        rows = db.execute(
            select(Product, Category.name)
            .outerjoin(Category, Product.category_id == Category.id)
            .order_by(Category.name, Product.sku)
        ).all()
        for product, category in rows:
            writer.writerow([
                product.sku, product.title, category or "Uncategorised",
                product.image_path or "", "",
            ])
    print(f"Exported {path}; fill the image_file column with exact filenames.")


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"sku", "image_file"}.issubset(reader.fieldnames):
            raise SystemExit("CSV must contain columns named sku and image_file.")
        result = []
        for line, row in enumerate(reader, start=2):
            sku = (row.get("sku") or "").strip()
            filename = (row.get("image_file") or "").strip()
            if not sku and not filename:
                continue
            if not sku or not filename:
                raise SystemExit(f"CSV line {line}: both sku and image_file are required.")
            result.append({"line": str(line), "sku": sku, "filename": filename})
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import product images by exact product SKU.")
    parser.add_argument("--export-template", metavar="CSV")
    parser.add_argument("--manifest", metavar="CSV")
    parser.add_argument("--images-dir", default="image_batches")
    parser.add_argument("--apply", action="store_true", help="Apply changes; omit for dry-run preview.")
    args = parser.parse_args()

    if args.export_template:
        export_template(Path(args.export_template).resolve())
        return 0
    if not args.manifest:
        parser.error("Provide --export-template or --manifest.")

    manifest_path = Path(args.manifest).resolve()
    images_dir = Path(args.images_dir).resolve()
    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    if not images_dir.is_dir():
        raise SystemExit(f"Images directory not found: {images_dir}")

    entries = load_manifest(manifest_path)
    if not entries:
        raise SystemExit("No image mappings found in manifest.")

    with SessionLocal() as db:
        products = {p.sku: p for p in db.scalars(select(Product)).all()}
        categories = {c.id: c for c in db.scalars(select(Category)).all()}
        seen = set()
        plan, errors = [], []

        for entry in entries:
            sku, filename, line = entry["sku"], entry["filename"], entry["line"]
            if sku in seen:
                errors.append(f"Line {line}: duplicate SKU {sku}")
                continue
            seen.add(sku)
            product = products.get(sku)
            if product is None:
                errors.append(f"Line {line}: SKU not found: {sku}")
                continue
            if Path(filename).name != filename or "/" in filename or "\\" in filename:
                errors.append(f"Line {line}: image_file must be a filename, not a path.")
                continue
            if Path(filename).suffix.lower() not in ALLOWED:
                errors.append(f"Line {line}: unsupported image extension: {filename}")
                continue
            source = images_dir / filename
            if not source.is_file():
                errors.append(f"Line {line}: image file missing: {filename}")
                continue
            category = categories.get(product.category_id)
            category_name = (category.name if category else "").strip().lower()
            folder = CATEGORY_FOLDERS.get(category_name)
            if not folder:
                errors.append(f"Line {line}: SKU {sku} has no supported category.")
                continue
            destination = UPLOADS / folder / filename
            if destination.exists() and destination.resolve() != source.resolve():
                errors.append(f"Line {line}: destination already exists: {destination}")
                continue
            plan.append((product, source, destination, f"{folder}/{filename}"))

        print(f"\nDRY RUN: {len(plan)} image(s) ready; {len(errors)} issue(s).")
        for product, source, destination, relpath in plan:
            print(f"  {product.sku} | {product.title} -> {relpath}")
        for error in errors:
            print("  ERROR:", error)
        if errors:
            print("\nNothing changed. Fix the errors and preview again.")
            return 2
        if not args.apply:
            print("\nNo files copied and no database changes made. Add --apply after checking.")
            return 0

        backup_dir = ROOT / "backups"
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f"image_paths_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with backup_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["sku", "old_image_path", "new_image_path"])
            for product, _src, _dst, relpath in plan:
                writer.writerow([product.sku, product.image_path or "", relpath])

        copied = []
        try:
            for product, source, destination, relpath in plan:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                    copied.append(destination)
                product.image_path = relpath
            db.commit()
        except Exception:
            db.rollback()
            for path in copied:
                path.unlink(missing_ok=True)
            raise

        print(f"\nSUCCESS: {len(plan)} product(s) updated.")
        print(f"Previous image paths backed up to: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
