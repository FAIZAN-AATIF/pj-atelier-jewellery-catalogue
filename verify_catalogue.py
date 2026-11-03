"""Verify exact catalogue totals and that every product has a distinct existing image."""
from collections import Counter
from pathlib import Path
from sqlalchemy import select
from app.main import SessionLocal, Product, Category

ROOT = Path(__file__).resolve().parent
with SessionLocal() as db:
    categories = {c.id: c.name for c in db.scalars(select(Category)).all()}
    products = db.scalars(select(Product)).all()
    counts = Counter(categories.get(p.category_id, "Unknown") for p in products)
    missing, paths = [], []
    for p in products:
        if not p.image_path:
            missing.append((p.sku, "empty image_path"))
            continue
        image = ROOT / "uploads" / p.image_path
        if not image.is_file():
            missing.append((p.sku, f"missing file: {p.image_path}"))
        paths.append(p.image_path)
    duplicates = len(paths) - len(set(paths))
    print("Categories:", len(categories))
    for name in sorted(counts):
        print(f"{name}: {counts[name]} products")
    print("Total products:", len(products))
    print("Products with image files:", len(paths) - len(missing))
    print("Duplicate image paths:", duplicates)
    print("Missing images:", len(missing))
    for item in missing[:20]:
        print("MISSING:", item)
    assert len(categories) == 8
    assert len(products) == 800
    assert all(counts[name] == 100 for name in categories.values())
    assert not missing
    assert duplicates == 0
    print("VERIFICATION PASSED")
