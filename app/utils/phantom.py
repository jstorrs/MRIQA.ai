"""Phantom localization.

Every ACR test starts by finding where the phantom is in the image.
This module provides one robust helper that returns the phantom center,
radius, and a binary mask.

The ACR Large Phantom is a 190 mm diameter cylinder; on a 250 mm FOV /
256 matrix that is roughly 195 px across. We localize by:
  1. Otsu-thresholding the image.
  2. Picking the largest connected component.
  3. Fitting a minimum enclosing circle (skimage.measure.regionprops).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi
from skimage.filters import threshold_otsu
from skimage.measure import label, regionprops

from .phantom_spec import PHANTOMS, PhantomSpec, default_phantom


@dataclass
class PhantomGeometry:
    cx_px: float          # phantom center, column (x) in pixels
    cy_px: float          # phantom center, row (y) in pixels
    radius_px: float      # equivalent radius in pixels
    mask: np.ndarray      # boolean image-shaped mask of the phantom interior

    def center_mm(self, pixel_spacing_mm: tuple[float, float]) -> tuple[float, float]:
        dy, dx = pixel_spacing_mm
        return self.cx_px * dx, self.cy_px * dy

    def radius_mm(self, pixel_spacing_mm: tuple[float, float]) -> float:
        dy, dx = pixel_spacing_mm
        return self.radius_px * 0.5 * (dx + dy)


def localize_phantom(image: np.ndarray, fill_holes: bool = True) -> PhantomGeometry:
    """Locate the phantom in a 2D MR image and return its center+radius+mask."""
    if image.ndim != 2:
        raise ValueError("localize_phantom expects a 2D image")

    img = image.astype(np.float32)
    # Guard against very low dynamic range
    if img.max() - img.min() < 1e-6:
        raise ValueError("Image has no signal")

    try:
        t = threshold_otsu(img)
    except ValueError:
        # threshold_otsu raises ValueError on a constant-signal image; fall
        # back to a midpoint threshold so segmentation can still proceed.
        t = (img.max() + img.min()) / 2.0

    binary = img > t
    if fill_holes:
        binary = ndi.binary_fill_holes(binary)

    lbl = label(binary)
    if lbl.max() == 0:
        raise ValueError("No phantom detected (empty mask after threshold)")

    regions = regionprops(lbl)
    regions.sort(key=lambda r: r.area, reverse=True)
    phantom_region = regions[0]
    mask = lbl == phantom_region.label

    cy, cx = phantom_region.centroid
    # Equivalent radius from area
    radius_px = np.sqrt(phantom_region.area / np.pi)

    return PhantomGeometry(cx_px=cx, cy_px=cy, radius_px=radius_px, mask=mask)


def detect_phantom_spec(
    image: np.ndarray,
    pixel_spacing_mm: tuple[float, float],
    candidates: dict[str, PhantomSpec] | None = None,
) -> PhantomSpec:
    """Pick the phantom spec whose nominal diameter is closest to the
    **left-right width** measured on ``image`` (typically ACR slice 1, or
    the sagittal localizer where the axial circumference also runs L-R).

    L-R is used rather than top-bottom or an area-equivalent diameter
    because air bubbles at the top of the phantom can shrink the mask
    along the A-P / S-I axis and skew an area-based estimate.

    Falls back to ``default_phantom`` when segmentation fails or returns
    an empty mask.
    """
    pool = candidates or PHANTOMS
    try:
        geom = localize_phantom(image)
        xs = np.where(geom.mask)[1]
        if xs.size == 0:
            return default_phantom()
        width_px = float(xs.max() - xs.min() + 1)
        measured_mm = width_px * pixel_spacing_mm[1]
    except (ValueError, IndexError):
        return default_phantom()
    return min(pool.values(), key=lambda s: abs(s.diameter_mm - measured_mm))


def phantom_quality_warnings(
    geom: PhantomGeometry,
    pixel_spacing_mm: tuple[float, float],
    spec: PhantomSpec,
) -> list[str]:
    """Heuristic checks on whether the detected phantom matches the selected
    spec.

    Returns a list of human-readable warning strings; an empty list means
    the detection looks plausible. Used by every QA test to flag situations
    where the upstream segmentation failed and any downstream numbers are
    therefore suspect.
    """
    out: list[str] = []
    rad_mm = geom.radius_px * 0.5 * (pixel_spacing_mm[0] + pixel_spacing_mm[1])
    lo, hi = spec.radius_plausible_mm
    if rad_mm < lo or rad_mm > hi:
        out.append(
            f"Detected phantom radius {rad_mm:.0f} mm is outside the expected range "
            f"({lo:.0f}–{hi:.0f} mm) for the {spec.name}. The segmentation may have "
            "included background or missed part of the phantom."
        )
    return out

