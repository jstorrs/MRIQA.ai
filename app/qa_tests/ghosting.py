"""Test 6 — Percent Signal Ghosting / PSG (ACR MR QC Manual 2015 §3.6)

Procedure
---------
* Use slice 7 (same image as PIU).
* Place a large circular ROI (~200 cm²) inside the phantom — same as PIU.
* Place four thin rectangular ROIs in air, just outside the phantom:
  top, bottom, left, right. Each ~1 cm × 4 cm (10 cm² each), oriented so
  the long axis is parallel to the nearest phantom edge.
* PSG = | ((top + bottom) − (left + right)) / (2 × large) |
* Action limit: PSG ≤ 0.030 (i.e. 3.0 %), reported as a fraction or
  percent depending on convention. The MVP reports a percentage.

Implementation
--------------
ROIs are sized in mm from PixelSpacing. The four air ROIs are centered
~10 mm outside the phantom radius along each cardinal direction. We
guard against the ROI falling off the image.
"""

from __future__ import annotations

import numpy as np
from matplotlib.patches import Circle, Ellipse

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import (
    circular_roi_mask, elliptical_roi_mask, radius_px_for_area_cm2,
)
from ..utils.phantom import localize_phantom, phantom_quality_warnings
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


_AIR_ROI_COLORS = {"top": "yellow", "bottom": "yellow", "left": "magenta", "right": "magenta"}


def _draw_ghosting(
    ax,
    *,
    cx: float,
    cy: float,
    r_large: float,
    rois: dict,
    means: dict[str, float],
    psg_pct: float,
) -> None:
    ax.add_patch(Circle((cx, cy), r_large, fill=False, edgecolor="cyan", lw=1.5))
    for name, (rcy, rcx, sy, sx) in rois.items():
        ax.add_patch(Ellipse(
            (rcx, rcy), width=2 * sx, height=2 * sy,
            fill=False, edgecolor=_AIR_ROI_COLORS[name], lw=1.5,
        ))
        ax.annotate(
            f"{name}\n{means[name]:.1f}", (rcx, rcy),
            color=_AIR_ROI_COLORS[name], fontsize=7, ha="center", va="center",
        )
    ax.set_title(f"Slice 7 — PSG = {psg_pct:.3f} %", fontsize=10)


def _mm_to_px(mm: float, spacing_mm: float) -> float:
    return mm / spacing_mm


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    spec = spec or series.spec
    large_area = spec.ghosting_large_roi_area_cm2
    air_long_mm = spec.ghosting_air_roi_long_mm
    air_short_mm = spec.ghosting_air_roi_short_mm
    air_offset_mm = spec.ghosting_air_offset_mm
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
            res.add_warning(w, severity="medium")

        # Large ROI
        r_large = radius_px_for_area_cm2(large_area, ps)
        r_large = min(r_large, geom.radius_px * 0.85)
        large_mask = circular_roi_mask(img.shape, geom.cy_px, geom.cx_px, r_large)
        s_large = float(img[large_mask].mean())

        # Air ROIs — semi-axes in px
        long_px_row = _mm_to_px(air_long_mm / 2.0, ps[0])
        long_px_col = _mm_to_px(air_long_mm / 2.0, ps[1])
        short_px_row = _mm_to_px(air_short_mm / 2.0, ps[0])
        short_px_col = _mm_to_px(air_short_mm / 2.0, ps[1])

        # geom.radius_px is a single scalar; for non-square pixels it conflates
        # the row- and column-axis radii. Acceptable for ACR phantom datasets
        # (PixelSpacing is square) but worth knowing if non-square data shows up.
        offset_row = geom.radius_px + _mm_to_px(air_offset_mm, ps[0])
        offset_col = geom.radius_px + _mm_to_px(air_offset_mm, ps[1])

        # Top (above): long axis horizontal -> wider in x (col), short in y (row)
        rois = {
            "top":    (geom.cy_px - offset_row, geom.cx_px,           short_px_row, long_px_col),
            "bottom": (geom.cy_px + offset_row, geom.cx_px,           short_px_row, long_px_col),
            "left":   (geom.cy_px,              geom.cx_px - offset_col, long_px_row, short_px_col),
            "right":  (geom.cy_px,              geom.cx_px + offset_col, long_px_row, short_px_col),
        }

        means: dict[str, float] = {}
        masks: dict[str, np.ndarray] = {}
        for name, (cy, cx, sy, sx) in rois.items():
            mask = elliptical_roi_mask(img.shape, cy, cx, sy, sx)
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
                    severity="medium",
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
