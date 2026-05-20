"""Test 4 — Slice Position Accuracy (ACR MR QC Manual 2015 §3.4)

Procedure
---------
Slices 1 and 11 contain a pair of vertical bars (a "wedge" pair) that
sit on either side of the phantom center near the top of each slice.
When the slice is correctly positioned, the two bars have equal length.

For each of slice 1 and slice 11:
  * Measure the length of the left bar and the right bar.
  * `bar_difference = left_length - right_length`  (mm)
  * The ACR reports `bar_difference / 2` as the slice-position offset.

Action limit: |bar_difference| ≤ 5 mm. The MVP reports the value and
flags pass/fail accordingly.

Implementation
--------------
* Find the phantom; restrict to a horizontal band just inside the
  superior edge.
* In that band, find the two vertical bright bars.
* For each bar, find its top and bottom row from the column profile and
  convert to mm.
"""

from __future__ import annotations

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import fwhm_from_profile
from ..utils.phantom import localize_phantom
from ..utils.viz import render_annotated
from .base import Measurement, TestResult

BAR_DIFF_TOLERANCE_MM = 5.0


def _measure_wedge_pair(image: np.ndarray, geom):
    """Return ((left_len_px, left_col), (right_len_px, right_col), search_box).

    Slice 1 / 11 wedge pair sits within the slice-thickness insert area
    near the top of the phantom in axial orientation.
    """
    H, W = image.shape
    # Search box near the *top* of the phantom (small y values)
    cy, cx, r = geom.cy_px, geom.cx_px, geom.radius_px
    y0 = max(0, int(cy - 0.95 * r))
    y1 = max(y0 + 8, int(cy - 0.55 * r))
    x0 = max(0, int(cx - 0.20 * r))
    x1 = min(W, int(cx + 0.20 * r))
    box = image[y0:y1, x0:x1]
    if box.size == 0:
        raise ValueError("Wedge search window is empty.")

    # Column means; expect two peaks
    col_means = box.mean(axis=0)
    thresh = np.percentile(col_means, 70)
    above = col_means > thresh
    runs = []
    in_run = False
    start = 0
    for i, v in enumerate(above):
        if v and not in_run:
            in_run = True; start = i
        elif not v and in_run:
            in_run = False; runs.append((start, i - 1))
    if in_run:
        runs.append((start, len(above) - 1))
    # Sort by mean intensity, keep top two, then order by column
    runs.sort(key=lambda r_: col_means[r_[0]:r_[1] + 1].mean(), reverse=True)
    runs = sorted(runs[:2], key=lambda r_: r_[0])
    if len(runs) < 2:
        raise ValueError("Could not detect two vertical wedge bars.")

    bar_cols_local = [(rr[0] + rr[1]) // 2 for rr in runs]

    # For each bar, get the column profile through the *full* image and measure FWHM
    left_col = x0 + bar_cols_local[0]
    right_col = x0 + bar_cols_local[1]
    # Vertical profile through the full phantom height
    y_top = max(0, int(cy - r))
    y_bot = min(H, int(cy + r))
    left_prof = image[y_top:y_bot, left_col]
    right_prof = image[y_top:y_bot, right_col]
    left_len_px = fwhm_from_profile(left_prof)
    right_len_px = fwhm_from_profile(right_prof)
    return (left_len_px, left_col), (right_len_px, right_col), (y0, y1, x0, x1)


def _run_one(image: np.ndarray, ps, label_prefix: str):
    geom = localize_phantom(image)
    (lL, lC), (rL, rC), box = _measure_wedge_pair(image, geom)
    left_mm = lL * ps[0]
    right_mm = rL * ps[0]
    bar_diff_mm = left_mm - right_mm
    return {
        "left_mm": left_mm,
        "right_mm": right_mm,
        "bar_diff_mm": bar_diff_mm,
        "left_col": lC,
        "right_col": rC,
        "geom": geom,
        "box": box,
    }


def run(series: DicomSeries) -> TestResult:
    res = TestResult(
        test_id="slice_position",
        test_name="Slice Position Accuracy",
        automated=True,
        passed=True,
    )
    try:
        ps = series.metadata.pixel_spacing_mm
        for acr_slice in (1, 11):
            img = series.slice(acr_slice).astype(np.float32)
            r = _run_one(img, ps, f"Slice {acr_slice}")
            diff = r["bar_diff_mm"]
            passed = abs(diff) <= BAR_DIFF_TOLERANCE_MM
            res.measurements.append(Measurement(
                label=f"Slice {acr_slice} bar-length difference",
                value=round(diff, 2),
                unit="mm",
                spec=f"|Δ| ≤ {BAR_DIFF_TOLERANCE_MM} mm",
                passed=passed,
            ))

            def _draw(ax, r=r, acr_slice=acr_slice):
                cy = r["geom"].cy_px
                # Plot vertical lines at the two bar columns spanning the
                # measured bar lengths.
                H = img.shape[0]
                # Approximate vertical center of bars at top of phantom
                y_top = max(0, int(r["geom"].cy_px - r["geom"].radius_px))
                y_left_end = y_top + int(r["left_mm"] / ps[0])
                y_right_end = y_top + int(r["right_mm"] / ps[0])
                ax.plot([r["left_col"], r["left_col"]], [y_top, y_left_end], color="cyan", lw=2)
                ax.plot([r["right_col"], r["right_col"]], [y_top, y_right_end], color="magenta", lw=2)
                ax.annotate(f"L={r['left_mm']:.1f}", (r["left_col"], y_left_end), color="cyan",
                            fontsize=8, ha="center", va="top",
                            xytext=(0, 8), textcoords="offset points")
                ax.annotate(f"R={r['right_mm']:.1f}", (r["right_col"], y_right_end), color="magenta",
                            fontsize=8, ha="center", va="top",
                            xytext=(0, 8), textcoords="offset points")
                ax.set_title(f"Slice {acr_slice} — bar Δ = {r['bar_diff_mm']:+.2f} mm", fontsize=10)

            res.annotated_images.append((f"Slice {acr_slice} — slice position",
                                         render_annotated(img, "", _draw)))

        res.passed = all(m.passed for m in res.measurements)
        res.notes = "Bar lengths are FWHM of vertical column profiles. Δ = left − right."

        # --- Detection-quality heuristics ---
        for m in res.measurements:
            if abs(m.value) > 20:
                res.add_warning(
                    f"{m.label}: |Δ| = {abs(m.value):.1f} mm is implausibly large — the wedge "
                    "detector may have caught the wrong feature. Check the overlay.",
                    severity="low",
                )
    except Exception as exc:
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
