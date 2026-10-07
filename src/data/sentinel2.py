from __future__ import annotations

from typing import Any
from datetime import date, timedelta

# B6 and B7 are needed for the published BAIS2 formulation.
BANDS = ["B2", "B3", "B4", "B6", "B7", "B8", "B8A", "B11", "B12"]
CLOUDY_SCL_CLASSES = [3, 8, 9, 10, 11]  # shadow, cloud, cirrus, snow/ice


def normalize_s2_metadata(properties: dict[str, Any], collection: str) -> dict[str, Any]:
    millis = properties.get("system:time_start")
    from datetime import datetime, timezone
    acquired = datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat() if millis is not None else properties.get("acquisition_datetime")
    return {"source_image_id": properties.get("system:id") or properties.get("system:index") or properties.get("source_image_id"), "acquisition_datetime": acquired, "cloud_percentage": properties.get("CLOUDY_PIXEL_PERCENTAGE", properties.get("cloud_percentage")), "sensor": "Sentinel-2", "collection": collection, "processing_source": "Google Earth Engine", "bands": BANDS}


def mask_s2_clouds(image):
    """Mask SCL shadow/cloud/cirrus/snow pixels and return scaled reflectance bands."""
    import ee
    scl = image.select("SCL")
    mask = scl.neq(CLOUDY_SCL_CLASSES[0])
    for klass in CLOUDY_SCL_CLASSES[1:]:
        mask = mask.And(scl.neq(klass))
    return image.select(BANDS).multiply(0.0001).updateMask(mask).copyProperties(image, image.propertyNames())


def query_sentinel2(config: dict[str, Any]) -> dict[str, Any]:
    import ee
    acq = config["acquisition"]
    ee_cfg = acq["earth_engine"]
    west, south, east, north = acq.get("aoi_bbox_wgs84", config["pilot"]["aoi_bbox_wgs84"])
    collection_id = ee_cfg["sentinel2_collection"]
    coll = (ee.ImageCollection(collection_id).filterBounds(ee.Geometry.Rectangle([west, south, east, north]))
            .filterDate(acq["date_start"], (date.fromisoformat(acq["date_end"]) + timedelta(days=1)).isoformat())).sort("system:time_start")
    queried = int(coll.size().getInfo())
    images = coll.toList(queried)
    accepted, rejected = [], []
    threshold = float(acq["cloud_threshold_pct"])
    for i in range(queried):
        img = ee.Image(images.get(i))
        props = img.toDictionary(["system:id", "system:index", "system:time_start", "CLOUDY_PIXEL_PERCENTAGE"]).getInfo()
        meta = normalize_s2_metadata(props, collection_id)
        cloud = meta["cloud_percentage"]
        if cloud is not None and float(cloud) > threshold:
            rejected.append({**meta, "reason": "scene_cloud_percentage_above_threshold"})
        else:
            accepted.append(meta)
    return {"images_queried": queried, "images_accepted": accepted, "images_rejected": rejected, "pixel_cloud_mask": "SCL classes 3,8,9,10,11; selected reflectance bands scaled by 0.0001", "warnings": ["Scene cloud percentage is a coarse prefilter; use mask_s2_clouds for pixel-level SCL masking before field reducers."]}
