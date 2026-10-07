# Pitch and demo guide (Greenovators 2026)

**Deck:** `reports/pitch/Parali_Se_Paisa_Greenovators2026.pptx` (editable, with speaker notes on every slide) and `.pdf`.
**Evidence:** `reports/research/RESEARCH_SUMMARY.md` (results) and `docs/RESEARCH_METHODS.md` (methods).
Every number in the deck is generated from `reports/research/results.json`.

## Before the pitch (morning of 8 Oct)

1. `python scripts/update_live_2026.py` downloads any new Sentinel-2 pass of Muktsar and the latest FIRMS NRT alerts, then rebuilds the results, figures, maps and deck. It takes about 5–10 minutes.
2. `$env:DATA_MODE='real'; python scripts/start_demo.py` starts the real-data mode. Log in as `official` with the password in `.demo/credentials.json`.
3. Open **Research Evidence** and check that the tiles show the latest image date.
4. Keep the PDF deck open as a fallback.

## 6-minute talk track

| Time | Slide | Say | Show |
|---|---|---|---|
| 0:00 | 1 | "Punjab's fire counts have collapsed. The burning hasn't. We can show it field by field." | Burn map |
| 0:30 | 2 | 18.8 Mt of straw; fire counts down 92%; over 90% of large fires now after 3 PM (iFOREST, SEVIRI) | Big numbers |
| 1:00 | 3 | "Every field, every 2–5 days, from free data, on a laptop." | Pipeline |
| 1:30 | 4 | **Fire alerts −79%, burn scars unchanged** (harmonised revisit) | f1 |
| 2:10 | 5 | **9 in 10 strict-tier burn candidates raised no fire alert in 2025**; smoke blinds optical sensors too | f2 + f3 |
| 2:50 | 6 | Rigour: naive dNBR flags 98% of fields; harvest-aware logic, thermal recall, proximity controls, blind human labels | f4 |
| 3:20 | 7 | A two-week window; repeat burners (4.6% of fields) do 34% of the burning | Map + f5 |
| 3:50 | 8 | Same 100 balers, 2.6× more burns pre-empted with risk ranking; early beats precise | f6 |
| 4:30 | **Live app** | Research Evidence → map toggles 2023/24/25 → 2026 pre-season risk → weekly straw forecast → a field's season events | App |
| 5:30 | 11–13 | ₹194 crore of straw in one district; 741 t CO₂e per 1,000 ha not burned; no hardware; honest limits; next: pilot | Close |

## Click path in the app (official login)

1. **Research Evidence**: read the tiles aloud, from fire alerts down to the 2026 harvest.
2. On the map, click **2023 → 2024 → 2025 burn scars**, then tick **VIIRS fire alerts**. The scars are everywhere; the dots are sparse.
3. Click **2026 pre-season risk**: "this is where we pre-book balers this week".
4. Scroll to the **2026 straw supply forecast** and the **pre-booking list**.
5. Open **Fields → any FTW field → Satellite tab** to show that field's harvest and burn dates for each season.
6. For the full operational loop of dispatch, buyer, certificate and farmer in Punjabi, switch to demo mode (`DATA_MODE=demo`) and say clearly that it uses synthetic fixtures.

## Likely judge questions

**How do you know a detected burn is real?**
- Two-thirds of VIIRS fire alerts (67% / 53% / 64% for 2023/24/25) have a Sentinel-2 burn scar within 500 m in the same window, which is independent thermal evidence.
- Every comparison has a proximity control.
- Human labels come from a blind, stratified before/after tool (`reports/research/label_tool/`), with precision and area estimated by the Olofsson et al. (2014) estimator. *[Insert the precision once labels are in.]*
- Precedent: Walker et al. (2022) reached 82% accuracy with Sentinel-2 against Punjab ground truth.

**Couldn't a dark field be wet or tilled soil?** Wet soil darkens SWIR more than NIR, so its NBR stays positive; char drives NBR negative. On 22 Nov 2025 rain darkened the whole district in true colour, and the detector did not fire.

**What about smoke and cloud?** Sen2Cor misses smoke. Clear-sky optical observations collapse to 4–33% of fields at the burning peak, but SWIR at 2.2 µm passes through, and the detector keeps 63–100% of fields usable.

**Fields are small for 20 m pixels.** Fields of The World polygons average 1.4 ha, about 35 pixels. Fields under 3 pixels are excluded, and partial burns are captured as the fraction of char-like pixels.

**How is this different from iFOREST or CEEW?** They report state-level burnt area at 100 m. We work field by field, separate harvest from fire, date each event, and turn the evidence into action: risk ranking, baler dispatch and no-burn certificates. We independently corroborate their after-overpass finding.

**Why is 2024 lower?** Opaque smog removed 3–21 Nov 2024. Char tilled in before 22 Nov was missed, so 2024 is a stated lower bound.

**What is the model accuracy?** The risk model is modest and evaluated honestly on an unseen season: AUC 0.65–0.69, with 2.3–2.7× lift in the top decile. The value shows in operations: 2.6× more burns pre-empted with the same fleet. Scores are relative ranks, not probabilities.

**Will farmers be penalised?** No. Field-level burn data is restricted to officials, the API labels it as not enforcement evidence, and the product's purpose is to pay for straw and speed up incentives.

**Do you need GPUs or paid data?** No. Everything runs on a laptop CPU from free Sentinel-2, VIIRS and ERA5 data. Scaling to another district is a configuration change.

**What is next?** Finish the labels, use Sentinel-1 radar for smog gaps and a paddy mask (a first attempt was inconclusive and is documented), and pilot in one block with a baler cooperative and a buyer.

## Submission checklist

- [ ] Deck (PPTX + PDF), refreshed by `update_live_2026.py`.
- [ ] `README.md` with the research section, `RESEARCH_SUMMARY.md` and `RESEARCH_METHODS.md`.
- [ ] Source code: `src/research/`, `scripts/`, `frontend/src/pages/research.tsx`, `src/api/routes/research.py`.
- [ ] Tests: `python -m pytest -q --basetemp=data/tmp/pytest` and `cd frontend; npm test`.
- [ ] Optional: labels in `data/real/labels/visual_labels_2025.csv`, then `python scripts/evaluate_visual_labels.py` and update the deck's validation line.
- [ ] Repository: bulk data is in `.gitignore`. The pushable tree is about 134 MB, with no file over 100 MB.
