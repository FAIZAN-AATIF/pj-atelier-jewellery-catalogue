# PJ Atelier Vercel + Supabase deployment

## Important
- Keep the original project and SQLite database as your backup.
- The production app must use Supabase Postgres and the `jewellery_images` Storage bucket.
- Never commit `.env`, database passwords, or the Supabase service-role key.
- The migration script requires the original `pj_catalogue.db` and `uploads/` directory.

## Supabase migration (run once from a local copy)
1. In Supabase Storage, keep `jewellery_images` public. The catalogue source images are JPG files.
2. In PowerShell, open this project folder and set these environment variables for the current terminal session: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET`.
3. `DATABASE_URL` must be the Supabase Transaction Pooler URI. For SQLAlchemy/psycopg, it may be entered as `postgresql+psycopg://...`; the script also converts `postgresql://` automatically.
4. Install dependencies: `py -m pip install -r requirements.txt`.
5. Run: `py scripts/migrate_to_supabase.py`.
6. Confirm the script reports 8 categories, 800 products and 800 product images.

## Vercel environment variables
Set `DATABASE_URL`, `APP_SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_BUCKET`, and `MAX_IMAGE_MB=8` in Vercel for Production. `OPENAI_API_KEY` is optional; AI suggestions remain unavailable if it is omitted.

## Deployment
Import the GitHub repository into Vercel with Root Directory `./`. Vercel will use `vercel.json` and `api/index.py`. Do not deploy until the Supabase migration has completed and all environment variables have been set.
