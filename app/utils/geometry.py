"""Generic geometry helpers used across QA tests."""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np


class FwhmFit(NamedTuple):
    """FWHM length plus sub-pixel left/right edge positions.

    ``left_x`` and ``right_x`` are in the same coordinate system as the
    caller's profile origin (set via the ``x0`` argument to
    :func:`fwhm_with_positions`). They are ``None`` when the profile is
    too short, flat, or never crosses the half-max threshold.
    """
    fwhm_px: float
    left_x: float | None
    right_x: float | None


def radius_px_for_area_cm2(area_cm2: float, pixel_spacing_mm) -> float:
    """Pixel radius of a circle whose physical area is ``area_cm2``.

    ``pixel_spacing_mm`` is ``(row, col)``; the row/col product gives the
    per-pixel area in mm².
    """
    area_mm2 = area_cm2 * 100.0
    px_area_mm2 = pixel_spacing_mm[0] * pixel_spacing_mm[1]
    return math.sqrt(area_mm2 / px_area_mm2 / math.pi)


def ellipse_axes_for_area_cm2(area_cm2: float, aspect_ratio: float) -> tuple[float, float]:
    """Return ``(long_axis_mm, short_axis_mm)`` for an ellipse of the requested area."""
    area_mm2 = area_cm2 * 100.0
    short_axis_mm = math.sqrt(4.0 * area_mm2 / (math.pi * aspect_ratio))
    return short_axis_mm * aspect_ratio, short_axis_mm


def contiguous_runs(mask) -> list[tuple[int, int]]:
    """Return inclusive ``(start, end)`` index pairs for every run of truthy
    values in a 1D sequence.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def circular_roi_mask(shape: tuple[int, int], cy: float, cx: float, radius_px: float) -> np.ndarray:
    """Return a boolean mask for a circular ROI."""
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= radius_px ** 2


def elliptical_roi_mask(
    shape: tuple[int, int],
    cy: float,
    cx: float,
    semi_y_px: float,
    semi_x_px: float,
) -> np.ndarray:
    """Return a boolean mask for an axis-aligned elliptical ROI."""
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return ((yy - cy) / semi_y_px) ** 2 + ((xx - cx) / semi_x_px) ** 2 <= 1.0


def square_roi_mask(shape: tuple[int, int], cy: float, cx: float, half_size_px: float) -> np.ndarray:
    """Return a boolean mask for a square ROI."""
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    return (np.abs(yy - cy) <= half_size_px) & (np.abs(xx - cx) <= half_size_px)


def fwhm_with_positions(profile: np.ndarray, x0: int = 0) -> FwhmFit:
    """FWHM (px) of a bright ramp over a low-signal baseline, plus the
    sub-pixel left/right column positions.

    The baseline is the 5th-percentile of the smoothed profile (the
    void floor below the ramp). ``x0`` is added to the returned
    positions so callers can pass a profile sliced out of a larger
    array and get back image-coordinate positions.
    """
    p = smooth_boxcar(np.asarray(profile, dtype=float), 3)
    base = float(np.percentile(p, 5))
    peak = float(p.max())
    if peak - base < 1e-6:
        return FwhmFit(0.0, None, None)
    half = base + 0.5 * (peak - base)
    above = np.where(p >= half)[0]
    if above.size < 2:
        return FwhmFit(0.0, None, None)
    lo, hi = int(above[0]), int(above[-1])

    if lo > 0:
        denom = p[lo] - p[lo - 1] + 1e-9
        lf = (lo - 1) + (half - p[lo - 1]) / denom
    else:
        lf = float(lo)

    if hi < len(p) - 1:
        denom = p[hi + 1] - p[hi] + 1e-9
        rf = hi + (half - p[hi]) / denom
    else:
        rf = float(hi)

    return FwhmFit(rf - lf, x0 + lf, x0 + rf)


def smooth_boxcar(arr: np.ndarray, window: int) -> np.ndarray:
    """Boxcar-smooth a 1D array. Used for FWHM/profile detection in QA tests."""
    return np.convolve(arr, np.ones(window) / window, mode="same")


def line_profile(image: np.ndarray, p0: tuple[float, float], p1: tuple[float, float], n: int = 200) -> np.ndarray:
    """Sample image along the segment p0->p1 with bilinear interpolation."""
    y0, x0 = p0
    y1, x1 = p1
    ys = np.linspace(y0, y1, n)
    xs = np.linspace(x0, x1, n)
    yi0 = np.floor(ys).astype(int)
    xi0 = np.floor(xs).astype(int)
    yi1 = np.clip(yi0 + 1, 0, image.shape[0] - 1)
    xi1 = np.clip(xi0 + 1, 0, image.shape[1] - 1)
    yi0 = np.clip(yi0, 0, image.shape[0] - 1)
    xi0 = np.clip(xi0, 0, image.shape[1] - 1)
    wy = ys - yi0
    wx = xs - xi0
    v00 = image[yi0, xi0]
    v01 = image[yi0, xi1]
    v10 = image[yi1, xi0]
    v11 = image[yi1, xi1]
    return (v00 * (1 - wy) * (1 - wx)
            + v01 * (1 - wy) * wx
            + v10 * wy * (1 - wx)
            + v11 * wy * wx)


def find_phantom_edges_along_line(image: np.ndarray, p0, p1, n: int = 400) -> tuple[float, float]:
    """Return (entry_index, exit_index) along the sampled segment using the
    half-max threshold. Useful for measuring an end-to-end diameter."""
    prof = line_profile(image, p0, p1, n=n)
    smooth = np.convolve(prof, np.ones(5) / 5.0, mode="same")
    high = float(smooth.max())
    low = float(smooth.min())
    if high - low < 1e-6:
        return 0.0, float(n - 1)
    half = low + 0.5 * (high - low)
    above = smooth >= half
    if not above.any():
        return 0.0, float(n - 1)
    idx = np.where(above)[0]
    return float(idx[0]), float(idx[-1])


def phantom_chord_endpoints(
    image: np.ndarray, p0, p1, n: int = 600,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Return ``((y_in, x_in), (y_out, x_out))`` where a line from ``p0`` to
    ``p1`` crosses the phantom (sub-pixel half-max edges), interpolated back
    to image coordinates.
    """
    entry, exit_ = find_phantom_edges_along_line(image, p0, p1, n=n)
    def _at(t: float) -> tuple[float, float]:
        f = t / (n - 1)
        return p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f
    return _at(entry), _at(exit_)
