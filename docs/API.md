# Action Platform API

Run the local prototype after explicit demo seeding:

```powershell
python scripts/seed_demo.py
python scripts/serve_api.py
```

The default database is `sqlite:///data/processed/action_platform.db`; set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL for PostgreSQL. The API ensures tables exist for local convenience; data seeding is never automatic. To use Alembic against a new empty database, choose its URL before migration and seeding:

```powershell
$env:DATABASE_URL = "sqlite:///data/processed/migrated_action_platform.db"
python -m alembic upgrade head
python scripts/seed_demo.py
```

Do not apply the initial migration over tables already created by `create_all`; for an existing matching schema, mark the baseline with `python -m alembic stamp head`. Interactive OpenAPI documentation is served at `/docs`. This prototype has no authentication and is intended for local synthetic demonstration, not public operational deployment.

All application endpoints are under `/api/v1/`:

| Area | Methods and paths |
|---|---|
| Health | `GET /health` |
| Fields | `GET /fields`, `GET /fields/{field_id}`, `GET /fields/{field_id}/history`, `GET /fields/{field_id}/intelligence` |
| Balers | `GET /balers`, `POST /balers`, `PATCH /balers/{baler_id}` |
| Buyers | `GET /buyers`, `POST /buyers`, `PATCH /buyers/{buyer_id}` |
| Dispatch | `POST /dispatch/optimise`, `GET /dispatch/runs/{dispatch_run_id}`, `POST /dispatch/runs/{dispatch_run_id}/confirm` |
| Collection | `GET /jobs`, `PATCH /jobs/{job_id}/state` |
| Verification | `POST /verification/start/{field_id}`, `GET /verification/{verification_id}`, `GET /verification/field/{field_id}`, `POST /verification/{verification_id}/observations`, `POST /verification/{verification_id}/evaluate`, `POST /verification/{verification_id}/manual-review`, `POST /verification/{verification_id}/close` |
| Certificates | `GET /certificates`, `GET /certificates/{certificate_id}`, `GET /certificates/{certificate_id}/file`, `POST /certificates/generate/{verification_id}` |

Dispatch requests can select `field_ids`. Risk, status, harvest evidence, and straw are recomputed from server-held feature records; request bodies cannot override them. Buyer capacity is reserved in the same transaction as the dispatch run, routes, stops, and collection jobs; PostgreSQL row locks and SQLite immediate transactions serialize reservation writers. Capacity increases through the prototype API are rejected unless performed through a future verified registry reconciliation path. Cancelling a collection releases its reservation. Job transitions are explicit: planned → accepted → en route → arrived → collecting → collected → delivered, with cancellation/failure paths where valid. Invalid jumps return HTTP 409.

Verification observations accept source image IDs and measurements, but the server calculates evidence class and overwrites the observation provenance with the field/case provenance. Evaluation time comes from the server. Certificate generation rechecks persisted chronological evidence and state. State-changing operations write `audit_events` rows. Responses preserve per-record provenance and identify the distance method.

The API uses SQLAlchemy models in `src/db/` and Pydantic request schemas in `src/api/schemas.py`. Set `DATABASE_URL` to `sqlite:///...` for local tests or a PostgreSQL URL (for example, `postgresql+psycopg://...`) with credentials supplied only in the environment. Do not commit credentials.
