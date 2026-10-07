# Post-harvest verification and prototype certificates

## Monitoring lifecycle

Cases move through explicit states: `NOT_STARTED`, `MONITORING`, `INSUFFICIENT_EVIDENCE`, `MANUAL_REVIEW_REQUIRED`, `BURN_SIGNAL_DETECTED`, `NO_BURN_VERIFIED`, and `CLOSED`. Monitoring starts with an explicit timestamp and configured 30-day deadline. Observations must be timezone-aware, belong to the case field, follow strict chronological order, and not be future-dated. Each record carries image references, indices/deltas, quality, FIRMS context, status candidate, and provenance.

## Evidence rules

Only `GOOD` quality images can be evaluated for burn/no-burn indicators. Strong burn evidence requires all configured large NBR and NDVI declines and BAIS2 increase. Multiple moderate changes require manual review. A single indicator is not decisive. Nearby FIRMS context can corroborate spectral signals; FIRMS context by itself becomes `UNCLEAR` and requests review. The absence of a FIRMS detection never contributes negative evidence. Poor imagery or mixed signals moves the case to `MANUAL_REVIEW_REQUIRED`.

`NO_BURN_INDICATORS_DETECTED` means only that one good-quality observation lacks the configured indicators; it does not prove that the field did not burn. Automated `NO_BURN_VERIFIED` requires at least three chronological, good-quality observations spanning 20 days with no credible burn signal, and the 30-day monitoring deadline reached. A high-confidence (`>= 0.8`) observed `SOWN` candidate can end monitoring early after the same minimum evidence threshold. The system never derives or invents a sowing date. Evidence thresholds are transparent engineering rules, not scientific validation.

## Certificate gate

The service reloads stored observations and recomputes eligibility at generation time. Only `NO_BURN_VERIFIED` passes; monitoring, insufficient evidence, manual review, and burn states are rejected. The PDF and offline QR payload include the certificate ID and a SHA-256 hash of canonical metadata. The QR is an integrity aid, not blockchain or a government verification service. Each PDF says **PROTOTYPE / DEMONSTRATION CERTIFICATE** and **NOT OFFICIAL GOVERNMENT CERTIFICATE**. Synthetic cases remain marked synthetic.

See `reports/verification_validation.json` for safe, burn, unclear, and insufficient synthetic scenarios.
