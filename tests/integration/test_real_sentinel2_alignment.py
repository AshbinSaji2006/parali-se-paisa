"""Offline proof that mixed native resolutions use one pixel grid for indices."""
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts.process_real_sentinel2 import _read_aligned_band


def _memory_raster(values, resolution):
    data = np.asarray(values, dtype="uint16")
    memory = MemoryFile()
    dataset = memory.open(driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
                          dtype="uint16", crs="EPSG:32643",
                          transform=from_origin(500000, 3400000, resolution, resolution))
    dataset.write(data, 1)
    dataset.close()
    dataset = memory.open()
    return memory, dataset


def test_ten_and_twenty_metre_bands_share_reference_grid():
    fine_memory, fine = _memory_raster(np.arange(1, 17).reshape(4, 4), 10)
    coarse_memory, coarse = _memory_raster(np.full((2, 2), 100), 20)
    try:
        transform = from_origin(500000, 3400000, 20, 20)
        fine_aligned = _read_aligned_band(fine, coarse.crs, transform, 2, 2)
        coarse_aligned = _read_aligned_band(coarse, coarse.crs, transform, 2, 2)
        assert fine_aligned.shape == coarse_aligned.shape == (2, 2)
        # Average resampling into uint16 uses nearest integer rounding.
        np.testing.assert_array_equal(fine_aligned, [[4, 6], [12, 14]])
        np.testing.assert_array_equal(coarse_aligned, np.full((2, 2), 100))
    finally:
        fine.close(); fine_memory.close(); coarse.close(); coarse_memory.close()


def test_categorical_mask_uses_nearest_resampling():
    source_memory, source = _memory_raster([[4, 6], [5, 7]], 20)
    try:
        aligned = _read_aligned_band(source, source.crs,
                                     from_origin(500000, 3400000, 20, 20), 2, 2,
                                     categorical=True)
        np.testing.assert_array_equal(aligned, [[4, 6], [5, 7]])
    finally:
        source.close(); source_memory.close()
