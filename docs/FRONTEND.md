# Frontend

The React and TypeScript application lives in `frontend/`. Vite proxies `/api` to the local FastAPI service; production deployments should set `VITE_API_BASE_URL` to the same-origin API path or a configured API host. React Router handles the application routes. TanStack Query caches server responses. Leaflet draws stored GeoJSON polygons and point markers; the default offline view deliberately has no external tile dependency. A tile URL is optional and must be accompanied by its attribution.

`npm ci`, `npm run typecheck`, `npm test`, and `npm run build` validate the client. `python scripts/export_openapi.py` and `npm run api:types` regenerate the OpenAPI-derived request types. `client.ts` also validates the critical product snapshot at runtime with Zod. The backend response model and API contract tests are the source of truth.

Access tokens remain in browser memory. Reloading or opening a new tab requires a new sign-in. Passwords and tokens are not written to local storage. Candidate states, normalized risk scores, distance proxies, provider availability, provenance and certificate disclaimers are visible at the point of use.
