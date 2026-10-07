# Judge demo

Use `python scripts/start_demo.py` from the project root. It resets only DEMO, SYNTHETIC and FIXTURE rows in `.demo/block4-local.db`, seeds historical evidence scenarios and hashed accounts, then starts the backend and Vite. On first start, account passwords are written to the ignored `.demo/credentials.json` file. The usernames are `official`, `operator`, `buyer` and `farmer`; the accounts cannot authenticate when `DEMO_MODE=false`. Resetting removes prototype PDFs and QR images for deleted demo certificate records only.

## Real-data evidence pass

Set `$env:DATA_MODE='real'` in PowerShell, then run `python scripts/start_demo.py`. The banner identifies the Sentinel-2 and ERA5 snapshot and labels its weak-proxy limits. Explore the Muktsar research fields and their observation histories. Real mode is read only, and dispatch, verification, and certificate writes are disabled because real buyer/baler registries and operational validation are unavailable. The login accounts remain demo accounts; the field observations shown in the product snapshot are real.

To present the end-to-end workflow afterward, stop both servers with Ctrl+C, set `$env:DATA_MODE='demo'`, and run `python scripts/start_demo.py` again. This second pass uses synthetic fields, buyers, balers, and recorded outcomes; identify it as the prototype workflow rather than real procurement evidence.

## Story

1. Sign in as `official`; explain the DEMO / SYNTHETIC banner and provider readiness.
2. Open the field map and select `SYNTHETIC-ACTION-FIELD-01`. Describe the rule-based harvested candidate, stored satellite values and quality, preliminary straw scenario estimate, and normalized burn-risk score.
3. Run dispatch once. Point out the DEMO baler and buyer, reserved tonnage, unserved panel, and straight-line planning proxy. Run it again to demonstrate the `ALREADY_ASSIGNED` guard.
4. Sign out and use `operator`. Move the assigned job through ACCEPTED, EN_ROUTE, ARRIVED, COLLECTING, COLLECTED and DELIVERED.
5. Sign back in as `official`. On the verification timeline, process the three stored historical synthetic observations. The backend evaluates them and makes `NO_BURN_VERIFIED` available only after the configured evidence rules pass.
6. Generate the prototype certificate. Open the public verification page to show the stored metadata checksum and prototype / non-government disclaimer.
7. Open `DEMO-MUK-0001` to show burn evidence blocks certification; open `DEMO-MUK-0002` to show uncertain evidence requires manual review.
8. Sign in as `farmer` to see the deterministic local farmer view. `buyer` is scoped to its own buyer record and loads.

`python scripts/run_block4_demo.py` runs this workflow through the actual API, persistence and actor permissions and writes `reports/e2e_validation.json`. `cd frontend && npm run e2e` runs it in the browser using a separate reset database and the installed system Chrome.

All scenarios, timestamps and accounts are synthetic or historical test data. The demo does not simulate live satellite acquisition, government approval, incentives, real transport routes, verified prices or payment.
