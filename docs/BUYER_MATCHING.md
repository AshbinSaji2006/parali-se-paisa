# Capacity-safe buyer matching

Buyer records have a stable ID, accepted residue types, buyer type, daily and remaining demand, optional moisture limit and price, operating hours, status, provenance, and source. The committed CSV entries are synthetic demo entities; they are not verified facilities or demand commitments.

## Eligibility and score

A buyer must be available, accept the field's residue type, allow its known moisture value, have enough remaining capacity for the entire field, and be within the configured maximum distance. Operating hours are checked only when a caller supplies an arrival time; no arrival estimate is manufactured from straight-line distance.

The configurable score is:

```text
50 × material compatibility
+ 25 × min(1, remaining demand / daily demand)
+ 25 × max(0, 1 − distance_km / maximum_distance_km)
```

The default maximum distance is 250 km. Price contributes zero by default because the fixtures contain no verified prices. A displayed price is never treated as genuine merely because the field is populated; price scoring only considers `REAL` buyers whose price is explicitly marked verified. Demo prices never enter that score.

## Reservation behavior

Fields are considered in descending supplied risk score, then descending straw amount. The matcher assigns the entire field to the highest-scoring buyer with enough remaining demand and subtracts that field's tonnage from the buyer's available balance. It never splits a field between buyers. Re-running through the API uses the persisted reduced buyer capacity, so accepted dispatches cannot oversubscribe a buyer. The API records one `buyer_allocations` row per routed field.

Distances are labelled `GEODESIC_PROXY` by default. Reasons explain compatibility, capacity, distance method, and exclusions. See `reports/buyer_matching_validation.json`.
