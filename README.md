# PJ Atelier — Jewellery Catalogue Studio

A local full-stack jewellery catalogue application built with FastAPI, SQLAlchemy, SQLite, and HTML/CSS/JavaScript.

## Included

- Public storefront with product browsing, search, category filtering, and product details.
- Admin login with JWT authentication.
- Admin dashboard with product counts, category management, product create/edit/archive, and draft/published status.
- Image upload with MIME-type and file-size validation.
- Category-specific image storage (`uploads/rings/`, `uploads/necklaces/`, etc.).
- Nested image paths preserved when creating and editing products.
- Optional AI image suggestions through the OpenAI API. AI suggestions are disabled until an API key is added.
- Fresh database automatically creates all eight categories and seeds 100 products in each category (800 total).
- CSV-based image importer that matches exact product SKUs and supports a safe dry run.
- Automatic generation of 800 distinct SKU-specific jewellery illustration SVGs (one per product) on first startup. They are unique vector catalogue illustrations, not photorealistic product photography.

## Quick start — Windows

1. Extract this ZIP to a folder such as `C:\PJ\pj_jewellery_catalogue`.
2. Install Python 3.10 or newer.
3. Double-click `start_windows.bat`.
4. On first run, it creates `venv`, installs packages, and creates `.env`.
5. Open:
   - Storefront: http://127.0.0.1:8000
   - Admin: http://127.0.0.1:8000/admin
   - API docs: http://127.0.0.1:8000/docs
6. Local first-run login: `admin` / `ChangeMe123!`.

Change `ADMIN_PASSWORD` and `APP_SECRET_KEY` in `.env` before sharing the project or exposing it beyond your own computer. Restart the server after changing `.env`.

## AI suggestions (optional)

AI image suggestions require a valid OpenAI API key. Add it to `.env`:

```env
OPENAI_API_KEY=your_api_key_here
OPENAI_VISION_MODEL=gpt-4.1-mini
```

Restart the server. Without a key, normal catalogue, admin, and image-upload features still work; only AI suggestions return an explanatory error.

## Product image import

The application creates and assigns a separate category-specific SVG illustration for every product at startup. Each image filename is derived from the product SKU, and the startup image-assignment step verifies exactly 100 products in each of the eight categories before assigning images.

For replacing these illustrations with supplier/photographer product photos, use `import_product_images.py`:

1. Back up `pj_catalogue.db` and `uploads/`.
2. Export real products: `python import_product_images.py --export-template product_image_manifest.csv`
3. Fill `image_file` for each actual SKU in the CSV.
4. Preview: `python import_product_images.py --manifest product_image_manifest.csv --images-dir image_batches`
5. Apply only after preview: `python import_product_images.py --manifest product_image_manifest.csv --images-dir image_batches --apply`

The importer uses exact SKUs and saves a backup of previous image paths. It does not overwrite existing files.

## Useful commands

```powershell
# Run the server manually
python -m uvicorn app.main:app --reload

# Verify all category counts and unique image files after first startup
python verify_catalogue.py

# Run smoke tests (requires installed dependencies)
python -m pytest -q

# Export current product-to-image mapping template
python import_product_images.py --export-template product_image_manifest.csv
```

## Data and safety notes

- The database is created automatically as `pj_catalogue.db` in the project root.
- Product images are files under `uploads/`; database rows store relative paths.
- Existing database files are not included in this ZIP; a clean database is initialized on first launch.
- The included seeded products are catalogue/demo entries. Verify actual product specifications, metal, purity, gemstone authenticity, dimensions, and pricing before using them commercially.
- This is a local assessment/demo application. For production deployment, add HTTPS, stronger secrets, rate limiting, backups, managed image storage, and a production database.
