"""Test 6 — Percent Signal Ghosting / PSG (ACR MR QC Manual 2015 §3.6)

Procedure
---------
* Use slice 7 (same image as PIU).
* Place a large circular ROI (~200 cm²) inside the phantom — same as PIU.
* Place four thin elliptical ROIs in air outside the phantom:
  top, bottom, left, right. Each ~10 cm² with a 4:1 aspect ratio, oriented so
  the long axis is parallel to the nearest phantom edge.
* PSG = | ((top + bottom) − (left + right)) / (2 × large) |
* Action limit: PSG ≤ 0.030 (i.e. 3.0 %), reported as a fraction or
  percent depending on convention. The MVP reports a percentage.

Implementation
--------------
ROIs are sized in mm from PixelSpacing. The four air ROIs are centered
between the phantom boundary and the FOV boundary along each cardinal
direction, with a small mandatory gap between the ROI's inner edge and
the phantom rim so partial-volume signal doesn't bleed in. We reject a
measurement when the prescribed ROI plus that gap cannot fit.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from matplotlib.patches import Circle, Ellipse

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import (
    circular_roi_mask, ellipse_axes_for_area_cm2, elliptical_roi_mask,
    radius_px_for_area_cm2,
)
from ..utils.phantom import localize_phantom, phantom_quality_warnings
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


_AIR_ROI_COLORS = {"top": "yellow", "bottom": "yellow", "left": "magenta", "right": "magenta"}


class _AirROI(NamedTuple):
    """Pixel geometry of one air ROI: centre + semi-axes (rows × cols)."""
    cy: float
    cx: float
    semi_y: float
    semi_x: float


def _draw_ghosting(
    ax,
    *,
    cx: float,
    cy: float,
    r_large: float,
    rois: dict[str, _AirROI],
    means: dict[str, float],
    psg_pct: float,
) -> None:
    ax.add_patch(Circle((cx, cy), r_large, fill=False, edgecolor="cyan", lw=1.5))
    for name, roi in rois.items():
        ax.add_patch(Ellipse(
            (roi.cx, roi.cy), width=2 * roi.semi_x, height=2 * roi.semi_y,
            fill=False, edgecolor=_AIR_ROI_COLORS[name], lw=1.5,
        ))
        ax.annotate(
            f"{name}\n{means[name]:.1f}", (roi.cx, roi.cy),
            color=_AIR_ROI_COLORS[name], fontsize=7, ha="center", va="center",
        )
    ax.set_title(f"Slice 7 — PSG = {psg_pct:.3f} %", fontsize=10)


def _mm_to_px(mm: float, spacing_mm: float) -> float:
    return mm / spacing_mm


_MIN_PHANTOM_GAP_MM = 5.0


def _air_rois(
    shape: tuple[int, int],
    geom,
    ps: tuple[float, float],
    area_cm2: float,
    aspect_ratio: float,
    min_gap_mm: float = _MIN_PHANTOM_GAP_MM,
) -> dict[str, _AirROI]:
    long_mm, short_mm = ellipse_axes_for_area_cm2(area_cm2, aspect_ratio)
    long_row = _mm_to_px(long_mm / 2.0, ps[0])
    long_col = _mm_to_px(long_mm / 2.0, ps[1])
    short_row = _mm_to_px(short_mm / 2.0, ps[0])
    short_col = _mm_to_px(short_mm / 2.0, ps[1])
    gap_row = _mm_to_px(min_gap_mm, ps[0])
    gap_col = _mm_to_px(min_gap_mm, ps[1])
    height, width = shape

    def midpoint(lo: float, hi: float, name: str) -> float:
        if hi < lo:
            raise ValueError(
                f"Air ROI '{name}' cannot fit between the phantom and FOV edge "
                f"(needs ≥{min_gap_mm:.0f} mm clearance); check FOV."
            )
        return (lo + hi) / 2.0

    horizontal_center = min(max(geom.cx_px, long_col), width - 1 - long_col)
    vertical_center = min(max(geom.cy_px, long_row), height - 1 - long_row)
    return {
        "top": _AirROI(
            cy=midpoint(short_row, geom.cy_px - geom.radius_px - short_row - gap_row, "top"),
            cx=horizontal_center, semi_y=short_row, semi_x=long_col,
        ),
        "bottom": _AirROI(
            cy=midpoint(geom.cy_px + geom.radius_px + short_row + gap_row, height - 1 - short_row, "bottom"),
            cx=horizontal_center, semi_y=short_row, semi_x=long_col,
        ),
        "left": _AirROI(
            cy=vertical_center,
            cx=midpoint(short_col, geom.cx_px - geom.radius_px - short_col - gap_col, "left"),
            semi_y=long_row, semi_x=short_col,
        ),
        "right": _AirROI(
            cy=vertical_center,
            cx=midpoint(geom.cx_px + geom.radius_px + short_col + gap_col, width - 1 - short_col, "right"),
            semi_y=long_row, semi_x=short_col,
        ),
    }


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    spec = spec or series.spec
    large_area = spec.ghosting_large_roi_area_cm2
    air_area = spec.ghosting_air_roi_area_cm2
    air_aspect = spec.ghosting_air_roi_aspect_ratio
    psg_threshold = spec.ghosting_threshold_percent
    res = TestResult(
        test_id="ghosting",
        test_name="Percent Signal Ghosting (PSG)",
        automated=True,
        passed=True,
    )
    with res.capture_failures():
        img = series.slice(7).astype(np.float32)
        ps = series.metadata.pixel_spacing_mm  # (row, col)
        geom = localize_phantom(img)
        for w in phantom_quality_warnings(geom, ps, spec):
            res.add_warning(w, degrade_to="medium")

        # Large ROI
        r_large = radius_px_for_area_cm2(large_area, ps)
        if r_large > geom.radius_px * 0.95:
            res.add_warning(
                f"Prescribed large ROI radius ({r_large:.1f} px) is close to or "
                f"exceeds the detected phantom radius ({geom.radius_px:.1f} px); "
                "the ROI may include non-phantom signal and depress the PSG denominator. "
                "Check the overlay.",
                degrade_to="medium",
            )
        large_mask = circular_roi_mask(img.shape, geom.cy_px, geom.cx_px, r_large)
        s_large = float(img[large_mask].mean())

        rois = _air_rois(img.shape, geom, ps, air_area, air_aspect)

        means: dict[str, float] = {}
        masks: dict[str, np.ndarray] = {}
        for name, roi in rois.items():
            mask = elliptical_roi_mask(img.shape, roi.cy, roi.cx, roi.semi_y, roi.semi_x)
            if mask.sum() < 5:
                raise ValueError(f"Air ROI '{name}' fell outside the image; check FOV.")
            masks[name] = mask
            means[name] = float(img[mask].mean())

        psg = abs(((means["top"] + means["bottom"]) - (means["left"] + means["right"])) / (2 * s_large))
        psg_pct = psg * 100.0

        m = Measurement(
            label="PSG",
            value=round(psg_pct, 3),
            unit="%",
            spec=f"≤ {psg_threshold:.1f} %",
            passed=psg_pct <= psg_threshold,
        )
        res.measurements.append(m)
        res.passed = bool(m.passed)
        res.notes = (
            f"Large ROI mean = {s_large:.1f}; "
            f"top/bot/left/right means = "
            f"{means['top']:.1f}/{means['bottom']:.1f}/{means['left']:.1f}/{means['right']:.1f}."
        )

        # --- Detection-quality heuristics ---
        # If any air ROI mean is more than ~10% of the phantom signal, the ROI almost
        # certainly clipped onto the phantom rather than sitting in air.
        for name, mean in means.items():
            ratio = mean / max(s_large, 1e-9)
            if ratio > 0.10:
                res.add_warning(
                    f"Air ROI '{name}' mean = {mean:.0f} ({ratio*100:.1f}% of phantom mean) — "
                    "likely overlapping the phantom or near a bright artifact. Check the overlay.",
                    degrade_to="medium",
                )

        res.annotated_images.append((
            f"Slice 7 — ghosting ROIs (PSG={psg_pct:.3f}%)",
            render_annotated(
                img, "",
                lambda ax: _draw_ghosting(
                    ax, cx=geom.cx_px, cy=geom.cy_px, r_large=r_large,
                    rois=rois, means=means, psg_pct=psg_pct,
                ),
            ),
        ))
    return res
