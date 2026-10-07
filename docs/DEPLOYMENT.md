# Deployment and local run

## Local development

1. Use Python 3.12 and Node.js 20 or newer.
2. Install backend dependencies with `python -m pip install -r requirements.txt` and frontend dependencies with `cd frontend && npm ci`.
3. Run `python scripts/start_demo.py`. This explicitly resets demo-only rows in a dedicated `.demo/` SQLite database, seeds fixture records and hashed demo accounts, then starts FastAPI on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`.
4. Read the local role passwords from `.demo/credentials.json`. This generated file is git-ignored.
5. To manage the default application database separately, copy `.env.example` to `.env`, adjust `DATABASE_URL`, then use `python scripts/reset_demo.py` or `python scripts/seed_demo.py` explicitly.

## Environment

`DATABASE_URL` accepts local SQLite or a SQLAlchemy PostgreSQL URL. PostgreSQL requires the included `psycopg[binary]` driver. `DEMO_MODE=true` is the local default. Live mode (`DEMO_MODE=false`) requires `JWT_SECRET` with at least 32 characters, rejects demo credentials, filters non-REAL rows, and blocks operational writes until verified providers exist. `CORS_ORIGINS` must be a comma-separated exact-origin allowlist. `VITE_API_BASE_URL` configures the frontend API route; optional `VITE_MAP_TILE_URL` and `VITE_MAP_ATTRIBUTION` set a basemap and its attribution.

## Database

For a blank deployment database, apply `alembic upgrade head`. An existing database created with the current application's `create_all` should be inspected before migration; if its schema exactly matches the migration, mark it with `alembic stamp head`. SQLite remains useful for the demo. PostgreSQL URL support and migration configuration are present, but a live PostgreSQL service was not available for verification in this build.

Seed identities with `python scripts/seed_accounts.py` and operational fixtures with `python scripts/seed_demo.py` only when `DEMO_MODE=true`. Use `python scripts/reset_demo.py` only when you intend to reset DEMO/SYNTHETIC/FIXTURE rows. Rows labelled REAL are preserved; foreign keys cause a mixed dependency to fail rather than deleting a non-demo record.

## Production-like build

`cd frontend && npm run typecheck && npm test && npm run build`. Serve the generated `frontend/dist/` through a TLS-terminating web server. Configure an explicit API base URL and CORS allowlist. Never seed demo accounts or fixtures into a live database. Provide a high-entropy shared `JWT_SECRET`. Configure centralized request throttling, TLS, secret rotation, database backups, monitoring, and access reviews before a public deployment. No deployment was performed or claimed in this project.

## Docker

Docker and Compose files are not included in this checkpoint. PostgreSQL support is configuration-only and was not verified against a running service. Use the local SQLite demo flow above for the hackathon walkthrough.
