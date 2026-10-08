"""Draw the stratified review sample and render its Sentinel-2 chips (internal chip store).

A stratified random sample of field-seasons is drawn per season, stratified by the detector's own
output (STRICT_BURN_CANDIDATE, LOOSE_BURN_CANDIDATE, HARVESTED_NO_BURN_CANDIDATE). For each sampled
field, three usable Sentinel-2 observations (before, candidate, after) are rendered as true-colour
and SWIR false-colour chips with the field outline, in shuffled order. Output is the internal chip
store reports/research/label_tool/chips_<year>.json plus sample_design_<year>.json. The reviewer
interface is built from it by scripts/build_reference_label_package.py, which withholds the stratum.
No label is produced here.
"""
from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from PIL import Image
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.chips import chip, field_mask, ring, stack_path  # noqa: E402
from src.research.events import RULE_VERSION, add_indices  # noqa: E402

TS = ROOT / "data" / "real" / "derived" / "timeseries"
OUT = ROOT / "reports" / "research" / "label_tool"
HALF = 20
SCALE = 5


def png(arr, edge) -> str:
    im = np.kron((np.clip(arr, 0, 1) * 255).astype(np.uint8), np.ones((SCALE, SCALE, 1), dtype=np.uint8))
    im[edge] = [255, 255, 0]
    img = Image.fromarray(im)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main(n_per_stratum: int = 80, year: int = 2025, seed: int = 7) -> None:
    ev = pd.read_parquet(TS / f"events_{year}.parquet")
    ids = pd.read_parquet(TS / "field_zone_ids.parquet")[["field_id", "zone"]]
    ev = ev.merge(ids, on="field_id")
    ev = ev[(ev.n_px >= 12) & ev.harvested]
    strata = {  # detector output; used for stratified sampling, never shown to reviewers
        "STRICT_BURN_CANDIDATE": ev[ev.burned_strict],
        "LOOSE_BURN_CANDIDATE": ev[ev.burned & ~ev.burned_strict],
        "HARVESTED_NO_BURN_CANDIDATE": ev[~ev.burned],
    }
    rng = np.random.default_rng(seed)
    ts = add_indices(pd.read_parquet(TS / f"field_timeseries_{year}.parquet"))
    ts = ts[ts.usable]
    tr = Transformer.from_crs(4326, 32643, always_xy=True)
    any_path = next(p for p in (ROOT / "data/real/s2_stack" / str(year)).glob("*.tif"))
    with rasterio.open(any_path) as s:
        T = s.transform
    items = []
    for name, df in strata.items():
        pick = df.sample(min(n_per_stratum, len(df)), random_state=int(rng.integers(1e9)))
        for _, f in pick.iterrows():
            obs = ts[ts.field_id == f.field_id].sort_values("date").reset_index(drop=True)
            post = obs[obs.date > f.harvest_date - pd.Timedelta(days=1)]
            if f.burned:
                cand = f.burn_date
            else:
                cand = post.loc[post.B8A.idxmin(), "date"] if len(post) else f.harvest_date
            k = obs.index[obs.date == cand]
            if len(k) == 0:
                continue
            k = int(k[0])
            dates = [obs.date[max(k - 1, 0)], obs.date[k], obs.date[min(k + 1, len(obs) - 1)]]
            x, y = tr.transform(f.centroid_lon, f.centroid_lat)
            r, c = rasterio.transform.rowcol(T, x, y)
            edge = ring(field_mask(r, c, int(f.zone), HALF), SCALE)
            frames = []
            for d in dates:
                rgb, sw = chip(stack_path(d), r, c, HALF)
                frames.append({"date": d.strftime("%d %b %Y"), "rgb": png(rgb, edge), "swir": png(sw, edge)})
            items.append({"field_id": f.field_id, "year": year, "stratum": name, "candidate_date": cand.strftime("%Y-%m-%d"),
                          "lon": round(float(f.centroid_lon), 5), "lat": round(float(f.centroid_lat), 5), "frames": frames})
    order = rng.permutation(len(items))
    items = [items[i] for i in order]
    # Internal chip store (with the stratum, needed for stratified estimation). It is not a review page:
    # scripts/build_reference_label_package.py builds the blind interface from it without the stratum.
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"chips_{year}.json").write_text(json.dumps({"year": year, "seed": seed, "rule_version": RULE_VERSION,
                                                        "note": "INTERNAL: contains detector strata; never give this file to reviewers.",
                                                        "items": items}), encoding="utf-8")
    meta = {s: int(len(d)) for s, d in strata.items()}
    (OUT / f"sample_design_{year}.json").write_text(json.dumps({"year": year, "population_by_stratum": meta, "rule_version": RULE_VERSION,
                                                         "population": "crop fields (clear-sky peak NDVI >= 0.6) with an observed harvest and >= 12 pixels",
                                                         "n_per_stratum": n_per_stratum, "seed": seed,
                                                         "items": len(items)}, indent=1), encoding="utf-8")
    print(f"wrote {len(items)} items; population {meta}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--n", type=int, default=80)
    a = ap.parse_args()
    main(n_per_stratum=a.n, year=a.year)
