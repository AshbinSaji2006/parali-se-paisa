# Block 3 Action Platform Report

## Phase status

- Phase 7, baler dispatch: **COMPLETE OFFLINE** — OR-Tools RoutingModel with eligibility, area/straw capacity, work windows, distance cap, risk/straw drop penalties, and explicit unserved reasons.
- Phase 8, buyer matching: **COMPLETE OFFLINE** — compatible buyers only, whole-field allocations, persisted demand reservations, and no oversubscription.
- Phase 9, verification and prototype certificate: **COMPLETE OFFLINE** — chronological evidence state machine; certificate gate requires `NO_BURN_VERIFIED`; PDF and offline QR generated.
- Phase 10, backend/database/API: **COMPLETE OFFLINE** — FastAPI, SQLAlchemy, SQLite, PostgreSQL-ready URL support, Alembic migration, audit events, and 27 documented API operations.

## Validation

The synthetic E2E workflow persisted a field, computed the existing rule-based intelligence, routed a DEMO baler with OR-Tools, reserved a DEMO buyer allocation, advanced collection through valid states, evaluated three chronological synthetic observations, and generated the prototype PDF/QR. Burn evidence blocks certificates; unclear imagery requires review; insufficient observations, no-baler, and no-buyer cases remain blocked/unserved.

## Completion gates

- Block 3: **COMPLETE OFFLINE**
- Offline verified: **YES**
- Live verified: **NO**
- Ready for Block 4: **YES**; Block 4 was not started.

## Provenance and limitations

There are two DEMO baler fixtures and two DEMO buyer fixtures; there are zero verified real balers or buyers in the registry. All action scenario data and generated verification evidence are synthetic. Geodesic distance is straight-line distance, not road distance or a travel-time estimate. Weather stays UNKNOWN without a current forecast. Rule-based burn risk is not probability; no-burn rules are uncalibrated engineering thresholds; buyer demand is synthetic; no live satellite verification, government integration, incentives, payments, or official certificate exists. API has no authentication.

Full repository tests: **193 passed, 0 failed, 1 skipped**.

## End-to-end run record

```json
{
  "workflow": [
    "field",
    "intelligence",
    "dispatch",
    "buyer",
    "collection",
    "verification",
    "prototype_certificate"
  ],
  "result": "PASS",
  "field_id": "SYNTHETIC-ACTION-FIELD-01",
  "dispatch_method": "ORTOOLS_V1",
  "baler_id": "DEMO-BALER-02",
  "buyer_id": "DEMO-BUYER-02",
  "collection_state": "DELIVERED",
  "verification_state": "NO_BURN_VERIFIED",
  "certificate_id": "PARALI-DEMO-833f1634-6006-4328-8180-cd82df3fa286",
  "certificate_sha256": "272208aec4c579de63e477b3d7ffdee7e168ae7f67c5c10e4ddd88995f6866d9",
  "certificate_pdf": "D:\\PROJECTS\\GREENOVATORS\\data\\processed\\certificates\\PARALI-DEMO-833f1634-6006-4328-8180-cd82df3fa286.pdf",
  "certificate_qr": "D:\\PROJECTS\\GREENOVATORS\\data\\processed\\certificates\\PARALI-DEMO-833f1634-6006-4328-8180-cd82df3fa286.png",
  "certificate_qr_payload": "{\"certificate_id\":\"PARALI-DEMO-833f1634-6006-4328-8180-cd82df3fa286\",\"sha256\":\"272208aec4c579de63e477b3d7ffdee7e168ae7f67c5c10e4ddd88995f6866d9\",\"verification\":\"OFFLINE_PROTOTYPE\"}",
  "data_class": "SYNTHETIC DEMONSTRATION ONLY",
  "notice": "Not a government determination or live agricultural operation",
  "test_suite": {
    "command": "python -m pytest -q",
    "passed": 193,
    "failed": 0,
    "skipped": 1,
    "status": "PASS",
    "scope": "Full offline repository suite; one external Earth Engine integration check skipped because it requires credentials/network access.",
    "observed_warnings": 3,
    "warning_source": "OR-Tools SWIG type deprecation warnings; no test failures."
  }
}
```
