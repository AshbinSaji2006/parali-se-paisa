"""Sentinel-2 indices. Inputs to public index functions are unit reflectance."""
from __future__ import annotations

import math


def _finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def normalized_difference(a, b):
    a, b = _finite(a), _finite(b)
    if a is None or b is None or a + b == 0:
        return None
    return (a - b) / (a + b)


def ndvi(b8, b4):
    return normalized_difference(b8, b4)


def nbr(b8a, b12):
    return normalized_difference(b8a, b12)


def bais2(b4, b6, b7, b8a, b12):
    """Filipponi (2018) BAIS2 using atmospherically corrected unit reflectance.

    BAIS2 = (1 - sqrt(B6*B7*B8A/B4)) * ((B12-B8A)/sqrt(B12+B8A) + 1)
    Undefined/non-real domains (including B4=0) return None, never a fabricated zero.
    Source: Filipponi, "BAIS2: Burned Area Index for Sentinel-2" (2018),
    https://www.mdpi.com/2504-3900/2/7/364
    """
    b4, b6, b7, b8a, b12 = map(_finite, (b4, b6, b7, b8a, b12))
    if any(v is None for v in (b4, b6, b7, b8a, b12)) or b4 == 0:
        return None
    first_radicand = b6 * b7 * b8a / b4
    second_radicand = b12 + b8a
    if first_radicand < 0 or second_radicand <= 0:
        return None
    return (1 - math.sqrt(first_radicand)) * ((b12 - b8a) / math.sqrt(second_radicand) + 1)
