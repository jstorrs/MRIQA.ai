"""Generic geometry helpers used across QA tests."""

from __future__ import annotations

import numpy as np
from scipy.interpolate import interp1d


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


def fwhm_from_profile(profile: np.ndarray) -> float:
    """Full-Width-Half-Maximum of a 1D profile in *pixel* units.

    Uses linear interpolation to estimate the half-max crossings, so the
    result is sub-pixel accurate.
    """
    p = np.asarray(profile, dtype=float)
    if p.size < 3:
        return 0.0
    baseline = float(np.median(p[: max(2, p.size // 10)]))
    peak = float(p.max())
    half = baseline + 0.5 * (peak - baseline)

    above = p >= half
    if not above.any():
        return 0.0

    # left crossing
    idx_above = np.where(above)[0]
    left_i = idx_above[0]
    right_i = idx_above[-1]

    if left_i > 0:
        x0, x1 = left_i - 1, left_i
        y0, y1 = p[x0], p[x1]
        left_x = x0 + (half - y0) / (y1 - y0 + 1e-12)
    else:
        left_x = float(left_i)

    if right_i < p.size - 1:
        x0, x1 = right_i, right_i + 1
        y0, y1 = p[x0], p[x1]
        right_x = x0 + (half - y0) / (y1 - y0 + 1e-12)
    else:
        right_x = float(right_i)

    return max(0.0, right_x - left_x)


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
