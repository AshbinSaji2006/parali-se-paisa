# Parali Se Paisa: 4-minute judge flow

**Deck:** [Parali_Se_Paisa_Greenovators2026.pptx](../reports/pitch/Parali_Se_Paisa_Greenovators2026.pptx) and PDF. The real-data figures are generated from the research outputs. The dispatch workflow uses separate synthetic demo records.

Keep the labels explicit while presenting:

- **REAL DATA** — Muktsar satellite observations and derived field histories.
- **RULE-BASED** — optical burn-candidate tiers and normalized risk score.
- **DEMO/SYNTHETIC** — baler, buyer, dispatch and operational records.
- **PROTOTYPE** — QR metadata check; it is not a signed or government certificate.

## Four-minute flow

| Time | Step and label | Judge flow / exact framing |
|---|---|---|
| 0:00–0:20 | Problem · DEMO CONTEXT | Straw has a short post-harvest handling window. Coordinating farmers, balers and buyers is the problem. |
| 0:20–0:45 | Solution · PROTOTYPE | Show the evidence-to-action concept. Explain that real research and synthetic operations are separated. |
| 0:45–1:15 | Muktsar map · REAL DATA | Open Research Evidence. Show the Sri Muktsar Sahib map and the 2025 layer. Explain field boundaries are model-derived research polygons. |
| 1:15–1:40 | One field · REAL DATA | Open a field detail and show its observations and provenance. It is a satellite time series, not a ground inspection. |
| 1:40–2:05 | Dense history · REAL DATA | Show the 74-scene, 12.6-million field-date research panel and quality flags for haze/cloud. |
| 2:05–2:35 | Field status · RULE-BASED | Explain STRICT_BURN_CANDIDATE and LOOSE_BURN_CANDIDATE. Read loose areas: 21,121 ha (2023), 10,566 ha (2024), 22,941 ha (2025). Strict areas are 649, 1,022 and 2,269 ha, but do not present as a trend because clean pre-event coverage changes by season. |
| 2:35–2:55 | Fire context · REAL DATA | In 2025, 8.8% of strict optical candidates had a matched VIIRS active-fire detection in the defined window. Say: “About 9 in 10 strict optical burn candidates had no matched VIIRS active-fire detection within the defined matching window.” FIRMS/VIIRS is corroborative thermal context, not ground truth. Never say satellites missed 90% of fires. |
| 2:55–3:10 | Straw estimate · REPORTED | The 12.1 lakh tonne figure was reported by The Tribune (reference 11 in the concept note); it is a news-reported estimate, not an official statistic. |
| 3:10–3:35 | Baler/buyer dispatch · DEMO/SYNTHETIC | Switch to demo mode. Show dispatch and buyer matching. Say the records are synthetic and the route is straight-line GEODESIC_PROXY, not road ETA. |
| 3:35–3:50 | Evidence workflow · DEMO/SYNTHETIC | Show evidence capture. Do not call it validated evidence or an audit. |
| 3:50–4:00 | No-burn certificate · PROTOTYPE | Show the QR metadata check. State it checks prototype metadata only; it is not a digital signature, government certificate, verified no-burn result or incentive approval. |

## Safe terminology

- Burn outputs: **RULE-BASED BURN CANDIDATE**, **STRICT_BURN_CANDIDATE**, **LOOSE_BURN_CANDIDATE**.
- FIRMS/VIIRS: corroborative thermal context, not validation or ground truth.
- Risk: normalized risk score, not probability.
- Route: straight-line **GEODESIC_PROXY**, not road routing or ETA.
- Certificate: prototype QR metadata check only.
- Detector: no independently validated accuracy; human labels completed: 0.

## Judge questions

**Are the candidates confirmed burns?** No. They are optical rule-based candidates. No independent human labels are complete.

**Why not compare strict area across years?** The strict tier requires a clean pre-event observation. Haze and cloud change the clean coverage available in each season.

**What does the VIIRS matching result mean?** It is corroborative thermal context within a defined time/radius window. It is not a field-level confirmation or a measure of fires missed.

**Is the operations workflow live?** No. The app's real mode is read-only. The dispatch, baler and buyer records shown in demo mode are synthetic.

**What is next?** Complete blinded human labels and run a bounded pilot with participating farmers, baler operators and buyers.
