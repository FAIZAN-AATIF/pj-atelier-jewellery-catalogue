# Technical notes for the candidate demonstration

## Suggested 3–5 minute walkthrough
1. Open the public storefront and show the live catalogue search and category filter.
2. Open the admin page and sign in using the local credentials.
3. Upload a jewellery image. Explain that upload validation happens on the server.
4. Generate AI suggestions (requires a configured OpenAI API key); explain the generated values are editable and must be reviewed.
5. Save as a draft, show that it is not public, then publish it and refresh the storefront.
6. Edit a field and refresh to demonstrate database persistence.
7. Show `/docs` and explain that backend routes enforce administrator authentication.

## Architecture decisions to explain
- SQLAlchemy models separate categories from products and use a foreign key for category association.
- The product image is stored as a file and the database stores its filename/path, avoiding large image blobs in ordinary rows.
- Publication status and archive state are separate. Public routes require `published` and not archived; the admin list can see drafts and archived entries.
- JWT bearer tokens protect administrative write/read routes. Credentials and AI keys are server-side environment values.
- AI output is explicitly a suggestion. The prompt avoids asserting purity, weight, or authenticity from visual appearance.
- SQLite makes the prototype straightforward to run locally; `DATABASE_URL` can point at PostgreSQL when a driver and database are configured.

## Be transparent during submission
This is an assessment prototype, not a production-ready commercial system. Configure secrets yourself, verify that your chosen OpenAI model is available, run the test suite, and make Git commits that reflect your actual work. Do not claim that hosted deployment, PostgreSQL, managed image storage, or full end-to-end browser testing has been completed unless you have actually configured and verified it.


### Seed catalogue
The first run against an empty database creates 100 published demo products in eight categories. Product artwork is bundled as 100 individual SVG files under `uploads/` and served through the existing `/uploads` static mount. These are illustrative vector images for assessment/demo use; replace them with authorized product photography for a production catalogue.
