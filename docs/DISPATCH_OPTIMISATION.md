# Offline baler dispatch

The dispatcher treats status and risk as decision-support candidates, not field truth. A field must have a supported `HARVESTED` candidate, usable coordinates, a positive straw estimate, and `GOOD` observation quality. Status source/confidence, risk score/method, weather status, and provenance travel with the decision.

## Solver and objective

`src/dispatch/optimizer.py` uses Google OR-Tools RoutingModel. Every field is one optional routing node, so it can be assigned to zero or one baler. The solver seeks to minimize distance cost and the penalty for leaving fields unserved:

```text
arc cost = distance_km × distance_cost_per_km × 100
drop penalty = base + risk_score × risk_priority_weight + straw_tonnes × straw_priority_weight
```

The default values are `100`, `1,000,000`, `100,000`, and `10,000`, respectively, in `config/dispatch.yaml`. Risk is a normalized rule score from 0 to 1, not a probability. Straw tonnage and risk raise the cost of leaving a field unserved. OR-Tools reports a feasible routing solution; this time-limited heuristic is not described as a proven global optimum.

## Constraints

- Baler must be `AVAILABLE` and have time remaining in its configured work window.
- Total assigned area cannot exceed daily acres; total estimated straw cannot exceed the optional straw capacity.
- Field service time is area in acres divided by baler service rate. The configurable concept assumption is about one acre per hour; these are planning assumptions, not observed operator performance.
- Total route distance, including return to the baler's starting location, is capped at 250 km by default. Each field appears at most once.
- Where a fixture provides a complete travel-time matrix, service and fixture drive minutes share the work-hour constraint. Otherwise only service minutes are constrained; the response explicitly says `SERVICE_ONLY_DISTANCE_NOT_TIME`.
- Unknown weather defaults to a warning. `BLOCK`, `WARN`, and `PERMIT` are configurable. No live forecast is invented. Unsuitable weather is blocked.
- When buyer matching is required, a field without a capacity-safe whole-field allocation is excluded with `NO_COMPATIBLE_BUYER`.

## Distance sources

`GeodesicDistanceProvider` returns straight-line Haversine distance with `GEODESIC_PROXY`; this is not road distance and provides no travel duration. `FixtureMatrixProvider` reads explicit offline distance entries and can include fixture-supplied durations. Missing fixture entries raise an error rather than silently inventing a route. No OSRM or live routing provider is configured.

## Unserved fields

Every ineligible or dropped field remains in `unserved_fields`, with reasons such as `HARVEST_EVIDENCE_INSUFFICIENT`, `WEATHER_UNSUITABLE`, `NO_AVAILABLE_BALER`, `CAPACITY_EXCEEDED`, `WORKING_HOURS_EXCEEDED`, and `DISTANCE_LIMIT`. When OR-Tools is unavailable, only the explicit `GREEDY_FALLBACK` method is used; the fallback is not reported as OR-Tools.

All committed fixture routes use `DEMO`/`SYNTHETIC` provenance. See `reports/dispatch_validation.json` for the offline validation run.
