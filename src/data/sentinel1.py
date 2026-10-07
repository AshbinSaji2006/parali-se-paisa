from __future__ import annotations

from typing import Any
from datetime import date, timedelta


def normalize_s1_metadata(properties: dict[str, Any], collection: str) -> dict[str, Any]:
    from datetime import datetime, timezone
    millis = properties.get("system:time_start")
    pols = properties.get("transmitterReceiverPolarisation") or properties.get("polarizations") or []
    return {"source_image_id": properties.get("system:id") or properties.get("system:index") or properties.get("source_image_id"), "acquisition_datetime": datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat() if millis is not None else properties.get("acquisition_datetime"), "sensor": "Sentinel-1", "collection": collection, "orbit_pass": properties.get("orbitProperties_pass", properties.get("orbit_pass")), "relative_orbit_number": properties.get("relativeOrbitNumber_start", properties.get("relativeOrbitNumber")), "instrument_mode": properties.get("instrumentMode", "IW"), "polarizations": pols, "has_vv": "VV" in pols, "has_vh": "VH" in pols, "processing_source": "Google Earth Engine"}


def query_sentinel1(config: dict[str, Any]) -> dict[str, Any]:
    import ee
    acq = config["acquisition"]
    ee_cfg = acq["earth_engine"]
    west, south, east, north = acq.get("aoi_bbox_wgs84", config["pilot"]["aoi_bbox_wgs84"])
    collection_id = ee_cfg["sentinel1_collection"]
    # Keep individual passes and polarization sets as individual acquisitions; no cross-orbit compositing here.
    coll = (ee.ImageCollection(collection_id).filterBounds(ee.Geometry.Rectangle([west, south, east, north]))
            .filterDate(acq["date_start"], (date.fromisoformat(acq["date_end"]) + timedelta(days=1)).isoformat())
            .filter(ee.Filter.eq("instrumentMode", ee_cfg.get("instrument_mode", "IW")))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .sort("system:time_start"))
    queried = int(coll.size().getInfo())
    items = coll.toList(queried)
    accepted = []
    for i in range(queried):
        img = ee.Image(items.get(i))
        props = img.toDictionary(["system:id", "system:index", "system:time_start", "orbitProperties_pass", "relativeOrbitNumber_start", "instrumentMode", "transmitterReceiverPolarisation"]).getInfo()
        accepted.append(normalize_s1_metadata(props, collection_id))
    return {"images_queried": queried, "images_accepted": accepted, "warnings": ["Filtered to IW mode and VV; VH is recorded when present. Ascending/descending and relative orbit are retained separately."]}
