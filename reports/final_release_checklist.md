# Block 4 final release checklist

- [x] Backend test suite: 197 passed, 1 skipped, 0 failed.
- [x] Frontend TypeScript check.
- [x] Frontend unit suite: 12 passed.
- [x] Production frontend build.
- [x] OpenAPI JSON export and TypeScript type generation.
- [x] Playwright browser map/field/dispatch journey.
- [x] Playwright unauthenticated gate and farmer mobile view.
- [x] Responsive overflow checked at 1366×768, 1920×1080, 768×1024, and 390×844.
- [x] API judge story: duplicate dispatch, operator transitions, safe/burn/unclear evidence, certificate integrity, PDF, and farmer access.
- [x] Repeated isolated demo reset and REAL-row preservation.
- [x] Final health check has zero failed checks (WARN only for unconfigured live providers and unavailable PostgreSQL service).
- [x] Playwright server cleanup checked; ports 8000/5173 have no leftover listeners.
- [ ] Live data/provider integration verified: not available.
- [ ] PostgreSQL service verified: not available.
- [ ] Docker/Compose deployment: not included.

**Release decision:** ready for an offline synthetic hackathon demo; not verified for live operations or public production deployment.
