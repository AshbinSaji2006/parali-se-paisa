"""Build a self-contained HTML labelling tool for burn-candidate validation.

A stratified random sample of 2025 field-seasons (rule-burned, rule-unburned) is drawn; for each,
three usable Sentinel-2 observations (before, candidate, after) are rendered as true-colour and
SWIR false-colour chips with the field outline. The rule decision is hidden and order is shuffled
so labels are independent of the detector. Labels are kept in the browser and exported as CSV to
data/real/labels/visual_labels_2025.csv (Tier B: multi-date human visual review).
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
from src.research.events import add_indices  # noqa: E402

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
    strata = {
        "rule_burn_strict": ev[ev.burned_strict],
        "rule_burn_loose_only": ev[ev.burned & ~ev.burned_strict],
        "rule_no_burn": ev[~ev.burned],
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
    # The stratum stays in the export (needed for stratified estimation) but is never displayed.
    OUT.mkdir(parents=True, exist_ok=True)
    html = (ROOT / "scripts" / "label_tool_template.html").read_text(encoding="utf-8")
    html = html.replace("burn-labels-2025-v1", f"burn-labels-{year}-v1").replace("visual_labels_2025.csv", f"visual_labels_{year}.csv")
    (OUT / f"label_burns_{year}.html").write_text(html.replace("__ITEMS__", json.dumps(items)), encoding="utf-8")
    meta = {s: int(len(d)) for s, d in strata.items()}
    (OUT / f"sample_design_{year}.json").write_text(json.dumps({"year": year, "population_by_stratum": meta,
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
