# Block 4 product and release report

## Delivered

- Official, baler operator, buyer, and farmer authentication with Argon2id password hashes, expiring JWTs, role checks, and field/job/record scoping.
- Offline-first React interface for field investigation, map, dispatch, collection, verification, certificate review, farmer updates, and system readiness.
- Product snapshot schema validation and generated OpenAPI TypeScript contract.
- Demo reset that only removes DEMO/SYNTHETIC/FIXTURE records and preserves REAL rows. Reset safety was exercised repeatedly against an isolated SQLite database containing a REAL field.
- Tracked Playwright server launcher with port preflight and child-process cleanup.
- Final health check and requested validation reports.

## Verification evidence

- Backend: 197 passed, 1 skipped, 0 failed. Three OR-Tools SWIG deprecation warnings.
- Frontend: TypeScript pass; 12 unit tests pass; production build pass.
- Playwright: 2 browser tests pass. The official field/dispatch path and farmer mobile path were exercised. Document width was checked at 1366×768, 1920×1080, 768×1024, and 390×844.
- API judge story: pass for dispatch persistence and duplicate protection, all operator states, safe/burn/unclear verification, certificate creation/integrity/PDF, and farmer permissions.
- Health check: WARN with no failing checks. It confirms local SQLite reset, REAL-row preservation, API health, login, product contract, OpenAPI export, and frontend build artifact.

## Boundaries

- Offline/demo path is verified with synthetic records. Live satellite acquisition, FIRMS, weather, verified pricing, transport routing, payments, and government determination are not verified or claimed.
- PostgreSQL URL/driver/migration support is configured, but no running PostgreSQL service was available for verification.
- Certificate checksum is a stored metadata SHA-256, not a digital signature and not a hash of the PDF bytes.
- Browser coverage for the full certificate, burn, manual-review, and operator transition path is supplied by the actual API integration story, not a single end-to-end browser session. Frontend unit tests cover translations and core views.
- Docker/Compose is not included in this checkpoint.

## Readiness

Ready for an offline synthetic hackathon demonstration. Do not present this build as a live satellite service or an official government decision system.
