"""Test 1 — Geometric Accuracy (ACR MR QC Manual 2015 §3.1)

Procedure
---------
* On slice 1: measure the *end-to-end* length of the phantom (single
  measurement, top-to-bottom).
* On slice 5: measure four diameters of the phantom — horizontal,
  vertical, and the two diagonals (45° and 135°).
* Expected end-to-end length: 148 mm (S/I, slice 1 short axis) and
  190 mm (slice 5 in-plane diameter).
* Action limit: each measured length within ±2 mm of nominal.

Implementation
--------------
We localize the phantom and then, for each requested orientation:
  - draw a long line through the centroid;
  - sample the image along that line with bilinear interpolation;
  - find the half-max crossings either side of the center;
  - convert pixels -> millimeters with PixelSpacing.

This is the same algorithm the ACR procedure asks the technologist to
do manually with the scanner's caliper tool.
"""

from __future__ import annotations

import math

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import find_phantom_edges_along_line
from ..utils.phantom import localize_phantom
from ..utils.viz import render_annotated
from .base import Measurement, TestResult

NOMINAL_SLICE1_MM = 148.0      # short-axis on slice 1 (between the bars)
NOMINAL_SLICE5_MM = 190.0      # in-plane diameter on slice 5
TOLERANCE_MM = 2.0


def _measure_length_along(image: np.ndarray, angle_deg: float, pixel_spacing_mm) -> tuple[float, tuple, tuple]:
    """Return (length_mm, p_entry_yx, p_exit_yx) for a chord through the
    phantom center at the given angle."""
    geom = localize_phantom(image)
    cy, cx = geom.cy_px, geom.cx_px

    # Build a long sample line that crosses the whole image
    L = max(image.shape) * 1.2
    a = math.radians(angle_deg)
    dy = math.sin(a)
    dx = math.cos(a)
    p0 = (cy - L / 2 * dy, cx - L / 2 * dx)
    p1 = (cy + L / 2 * dy, cx + L / 2 * dx)

    entry, exit_ = find_phantom_edges_along_line(image, p0, p1, n=600)
    # Convert sample indices back into image coordinates
    ys = np.linspace(p0[0], p1[0], 600)
    xs = np.linspace(p0[1], p1[1], 600)
    y_in, x_in = ys[int(entry)], xs[int(entry)]
    y_out, x_out = ys[int(exit_)], xs[int(exit_)]

    # Length in mm: PixelSpacing = (row_mm, col_mm)
    dy_mm = (y_out - y_in) * pixel_spacing_mm[0]
    dx_mm = (x_out - x_in) * pixel_spacing_mm[1]
    length_mm = math.hypot(dy_mm, dx_mm)
    return length_mm, (y_in, x_in), (y_out, x_out)


def run(series: DicomSeries) -> TestResult:
    res = TestResult(
        test_id="geometric_accuracy",
        test_name="Geometric Accuracy",
        automated=True,
        passed=True,
    )
    try:
        # ----- Slice 1 -----
        img1 = series.slice(1)
        len1_mm, p1a, p1b = _measure_length_along(img1, 90.0, series.metadata.pixel_spacing_mm)
        m1 = Measurement(
            label="Slice 1 — superior-inferior length",
            value=round(len1_mm, 2),
            unit="mm",
            spec=f"{NOMINAL_SLICE1_MM} ± {TOLERANCE_MM} mm",
            passed=abs(len1_mm - NOMINAL_SLICE1_MM) <= TOLERANCE_MM,
        )
        res.measurements.append(m1)

        def _draw_slice1(ax):
            ax.plot([p1a[1], p1b[1]], [p1a[0], p1b[0]], color="cyan", lw=2)
            ax.annotate(
                f"{len1_mm:.1f} mm",
                xy=((p1a[1] + p1b[1]) / 2, (p1a[0] + p1b[0]) / 2),
                color="cyan",
                fontsize=9,
                xytext=(8, 0),
                textcoords="offset points",
            )

        res.annotated_images.append(("Slice 1: superior-inferior length",
                                     render_annotated(img1, "Slice 1 — geometric accuracy", _draw_slice1)))

        # ----- Slice 5 -----
        img5 = series.slice(5)
        directions = [
            ("Horizontal (L-R)", 0.0, NOMINAL_SLICE5_MM),
            ("Vertical (A-P)",   90.0, NOMINAL_SLICE5_MM),
            ("Diagonal 45°",     45.0, NOMINAL_SLICE5_MM),
            ("Diagonal 135°",    135.0, NOMINAL_SLICE5_MM),
        ]
        endpoints = []
        for label, ang, nominal in directions:
            length_mm, pa, pb = _measure_length_along(img5, ang, series.metadata.pixel_spacing_mm)
            passed = abs(length_mm - nominal) <= TOLERANCE_MM
            res.measurements.append(Measurement(
                label=f"Slice 5 — {label}",
                value=round(length_mm, 2),
                unit="mm",
                spec=f"{nominal} ± {TOLERANCE_MM} mm",
                passed=passed,
            ))
            endpoints.append((label, pa, pb, length_mm))

        def _draw_slice5(ax):
            colors = ["cyan", "magenta", "yellow", "lime"]
            for (label, pa, pb, L), c in zip(endpoints, colors):
                ax.plot([pa[1], pb[1]], [pa[0], pb[0]], color=c, lw=1.6)
                ax.annotate(
                    f"{L:.1f}", xy=((pa[1] + pb[1]) / 2, (pa[0] + pb[0]) / 2),
                    color=c, fontsize=8, xytext=(6, 6), textcoords="offset points",
                )

        res.annotated_images.append(("Slice 5: four diameters",
                                     render_annotated(img5, "Slice 5 — geometric accuracy", _draw_slice5)))

        res.passed = all(m.passed for m in res.measurements)
        res.notes = (
            "End-to-end lengths measured via half-max edges along chords through the centroid. "
            f"Nominal slice-1 length {NOMINAL_SLICE1_MM} mm, slice-5 diameter {NOMINAL_SLICE5_MM} mm, "
            f"tolerance ±{TOLERANCE_MM} mm."
        )

        # --- Detection-quality heuristics ---
        for m in res.measurements:
            # Reasonable physical range for ACR Large Phantom diameters
            if m.value < 100 or m.value > 230:
                res.add_warning(
                    f"{m.label}: measured {m.value} mm is far outside the expected "
                    "phantom geometry — likely a phantom-edge detection error, not a real "
                    "geometric failure. Check the overlay.",
                    severity="low",
                )
            elif abs(m.value - (NOMINAL_SLICE1_MM if "Slice 1" in m.label else NOMINAL_SLICE5_MM)) > 15:
                res.add_warning(
                    f"{m.label}: large deviation from nominal ({m.value} mm) — verify the "
                    "measurement line in the overlay crosses the phantom edges cleanly.",
                    severity="medium",
                )
    except Exception as exc:  # pragma: no cover - defensive
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
