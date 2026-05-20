"""Test 3 — Slice Thickness Accuracy (ACR MR QC Manual 2015 §3.3)

Procedure
---------
On slice 1, the phantom contains a pair of high-signal ramps (the upper
and lower bars within the small slice-thickness insert at the center).
The ACR formula is:

    slice_thickness = 0.2 * (top * bottom) / (top + bottom)

where `top` and `bottom` are the FWHM ramp lengths in millimetres
measured along the same horizontal line that bisects each ramp. The 0.2
factor comes from the 10:1 wedge geometry baked into the phantom.

Expected: 5.0 mm. Action limit: ±0.7 mm.

Implementation
--------------
We locate the slice-thickness insert (a small bright bar pair near the
center of slice 1). The insert sits just below the central crosshair of
the phantom. We:

  1.  Localize the phantom and find a small search window centered on it.
  2.  Detect the two bright horizontal bars by row-wise mean above a
      threshold.
  3.  For each bar, take a row profile through its center, compute the
      FWHM in pixels, convert to mm with PixelSpacing.
  4.  Apply the 0.2 × top × bottom / (top + bottom) formula.

The localization is heuristic and may need user adjustment for very
unusual scanner setups; the result image shows the detected bars so the
user can sanity-check.
"""

from __future__ import annotations

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import fwhm_from_profile, line_profile
from ..utils.phantom import localize_phantom
from ..utils.viz import render_annotated
from .base import Measurement, TestResult

NOMINAL_THICKNESS_MM = 5.0
THICKNESS_TOLERANCE_MM = 0.7


def _detect_ramp_bars(image: np.ndarray, cy_px: float, cx_px: float, phantom_radius_px: float):
    """Return ((top_row, bottom_row), (left_col, right_col)) bounding box of the
    ramp-pair near the center of the phantom.

    The slice-thickness insert is a short pair of bright bars roughly
    20 mm long, sitting just inferior to the geometric center of slice 1.
    """
    H, W = image.shape
    # Search window: small box around phantom center
    win_h = int(0.15 * phantom_radius_px * 2)
    win_w = int(0.35 * phantom_radius_px * 2)
    y0 = max(0, int(cy_px) - win_h // 2)
    y1 = min(H, int(cy_px) + win_h // 2)
    x0 = max(0, int(cx_px) - win_w // 2)
    x1 = min(W, int(cx_px) + win_w // 2)
    box = image[y0:y1, x0:x1]

    # Row-mean profile inside the box; bars appear as two peaks
    row_means = box.mean(axis=1)
    if row_means.size < 4:
        raise ValueError("Slice-thickness ROI window too small.")
    thresh = np.percentile(row_means, 75)
    above = row_means > thresh
    # Find connected runs of True; expect two
    runs = []
    in_run = False
    start = 0
    for i, v in enumerate(above):
        if v and not in_run:
            in_run = True
            start = i
        elif not v and in_run:
            in_run = False
            runs.append((start, i - 1))
    if in_run:
        runs.append((start, len(above) - 1))
    # keep two strongest
    runs.sort(key=lambda r: row_means[r[0]:r[1] + 1].mean(), reverse=True)
    runs = sorted(runs[:2], key=lambda r: r[0])
    if len(runs) < 2:
        raise ValueError("Could not detect two slice-thickness ramp bars on slice 1.")

    top_row = y0 + (runs[0][0] + runs[0][1]) // 2
    bot_row = y0 + (runs[1][0] + runs[1][1]) // 2
    return (top_row, bot_row), (x0, x1)


def run(series: DicomSeries) -> TestResult:
    res = TestResult(
        test_id="slice_thickness",
        test_name="Slice Thickness Accuracy",
        automated=True,
        passed=True,
    )
    try:
        img = series.slice(1).astype(np.float32)
        ps = series.metadata.pixel_spacing_mm
        geom = localize_phantom(img)

        (top_row, bot_row), (x0, x1) = _detect_ramp_bars(img, geom.cy_px, geom.cx_px, geom.radius_px)

        # Take a horizontal profile through each ramp bar
        top_profile = img[top_row, x0:x1]
        bot_profile = img[bot_row, x0:x1]
        top_fwhm_px = fwhm_from_profile(top_profile)
        bot_fwhm_px = fwhm_from_profile(bot_profile)

        top_mm = top_fwhm_px * ps[1]
        bot_mm = bot_fwhm_px * ps[1]
        if top_mm + bot_mm < 1e-6:
            raise ValueError("Failed to fit FWHM on slice-thickness ramps.")

        thickness_mm = 0.2 * (top_mm * bot_mm) / (top_mm + bot_mm)

        m = Measurement(
            label="Measured slice thickness",
            value=round(thickness_mm, 2),
            unit="mm",
            spec=f"{NOMINAL_THICKNESS_MM} ± {THICKNESS_TOLERANCE_MM} mm",
            passed=abs(thickness_mm - NOMINAL_THICKNESS_MM) <= THICKNESS_TOLERANCE_MM,
        )
        res.measurements.append(m)
        res.measurements.append(Measurement("Top ramp FWHM", round(top_mm, 2), "mm"))
        res.measurements.append(Measurement("Bottom ramp FWHM", round(bot_mm, 2), "mm"))
        res.passed = bool(m.passed)
        res.notes = (
            "Slice thickness = 0.2 × top × bot / (top + bot), with FWHM measured horizontally "
            "across the two detected ramp bars in the slice-thickness insert."
        )

        # --- Detection-quality heuristics ---
        if thickness_mm < 1.0 or thickness_mm > 15.0:
            res.add_warning(
                f"Measured thickness {thickness_mm:.2f} mm is implausible — likely the ramp "
                "detector landed on the wrong features. Check the overlay.",
                severity="low",
            )
        if top_mm < 5 or bot_mm < 5:
            res.add_warning(
                f"One ramp FWHM is very short (top={top_mm:.1f} mm, bot={bot_mm:.1f} mm) — "
                "low SNR or wrong ROI. Check the overlay.",
                severity="medium",
            )
        if top_mm and bot_mm:
            asymmetry = abs(top_mm - bot_mm) / max(top_mm, bot_mm)
            if asymmetry > 0.4:
                res.add_warning(
                    f"Top and bottom ramp FWHM differ by {asymmetry*100:.0f}% — "
                    "geometry of the slice-thickness insert may not have been detected correctly.",
                    severity="medium",
                )

        def _draw(ax):
            ax.plot([x0, x1 - 1], [top_row, top_row], color="cyan", lw=1.5)
            ax.plot([x0, x1 - 1], [bot_row, bot_row], color="magenta", lw=1.5)
            ax.annotate(f"top FWHM={top_mm:.2f} mm", (x1, top_row), color="cyan", fontsize=8,
                        ha="left", va="center", xytext=(4, 0), textcoords="offset points")
            ax.annotate(f"bot FWHM={bot_mm:.2f} mm", (x1, bot_row), color="magenta", fontsize=8,
                        ha="left", va="center", xytext=(4, 0), textcoords="offset points")
            ax.set_title(f"Slice 1 — slice thickness {thickness_mm:.2f} mm", fontsize=10)

        res.annotated_images.append((f"Slice 1 — slice thickness {thickness_mm:.2f} mm",
                                     render_annotated(img, "", _draw)))
    except Exception as exc:
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
