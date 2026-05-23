"""Test 1 — Geometric Accuracy, axial (ACR MR QC Manual 2015 §3.1)

Procedure
---------
On the axial ACR phantom series, measure four in-plane diameters
through the phantom center:

* **Slice 5** — four diameters (horizontal, vertical, 45°, 135°).
* **Slice 1** — two diameters (horizontal, vertical).

Nominal diameter and the ± action limit come from ``series.spec`` so the
same algorithm runs unchanged for Large and Medium phantoms.

The superior-inferior length check belongs to the sagittal localizer and
is handled by ``app.qa_tests.localizer_geometry`` as a separate analysis;
it is not measurable on an axial slice.

Implementation
--------------
We localize the phantom and, for each requested orientation, draw a chord
through the centroid, sample with bilinear interpolation, find the
half-max crossings, and convert pixels → mm with PixelSpacing.
"""

from __future__ import annotations

import math

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import find_phantom_edges_along_line
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def _measure_length_along(image: np.ndarray, angle_deg: float, pixel_spacing_mm) -> tuple[float, tuple, tuple]:
    """Return (length_mm, p_entry_yx, p_exit_yx) for a chord through the
    phantom center at the given angle."""
    geom = localize_phantom(image)
    cy, cx = geom.cy_px, geom.cx_px

    L = max(image.shape) * 1.2
    a = math.radians(angle_deg)
    dy = math.sin(a)
    dx = math.cos(a)
    p0 = (cy - L / 2 * dy, cx - L / 2 * dx)
    p1 = (cy + L / 2 * dy, cx + L / 2 * dx)

    entry, exit_ = find_phantom_edges_along_line(image, p0, p1, n=600)
    ys = np.linspace(p0[0], p1[0], 600)
    xs = np.linspace(p0[1], p1[1], 600)
    y_in, x_in = ys[int(entry)], xs[int(entry)]
    y_out, x_out = ys[int(exit_)], xs[int(exit_)]

    dy_mm = (y_out - y_in) * pixel_spacing_mm[0]
    dx_mm = (x_out - x_in) * pixel_spacing_mm[1]
    length_mm = math.hypot(dy_mm, dx_mm)
    return length_mm, (y_in, x_in), (y_out, x_out)


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    if spec is None:
        spec = series.spec
    nominal_d = spec.diameter_mm
    tol = spec.length_tolerance_mm
    res = TestResult(
        test_id="geometric_accuracy",
        test_name="Geometric Accuracy",
        automated=True,
        passed=True,
    )
    try:
        ps = series.metadata.pixel_spacing_mm

        # ----- Axial slice 1: two diameters -----
        img1 = series.slice(1)
        slice1_dirs = [("Horizontal (L-R)", 0.0), ("Vertical (A-P)", 90.0)]
        s1_endpoints = []
        for label, ang in slice1_dirs:
            length_mm, pa, pb = _measure_length_along(img1, ang, ps)
            res.measurements.append(Measurement(
                label=f"Slice 1 — {label} diameter",
                value=round(length_mm, 2),
                unit="mm",
                spec=f"{nominal_d} ± {tol} mm",
                passed=abs(length_mm - nominal_d) <= tol,
            ))
            s1_endpoints.append((label, pa, pb, length_mm))

        def _draw_slice1(ax):
            colors = ["cyan", "magenta"]
            for (label, pa, pb, L), c in zip(s1_endpoints, colors):
                ax.plot([pa[1], pb[1]], [pa[0], pb[0]], color=c, lw=1.8)
                ax.annotate(f"{L:.1f}", xy=((pa[1] + pb[1]) / 2, (pa[0] + pb[0]) / 2),
                            color=c, fontsize=8, xytext=(6, 6), textcoords="offset points")

        res.annotated_images.append((
            "Slice 1: horizontal & vertical diameters",
            render_annotated(img1, "Slice 1 — geometric accuracy", _draw_slice1)))

        # ----- Axial slice 5: four diameters -----
        img5 = series.slice(5)
        slice5_dirs = [
            ("Horizontal (L-R)", 0.0),
            ("Vertical (A-P)",   90.0),
            ("Diagonal 45°",     45.0),
            ("Diagonal 135°",    135.0),
        ]
        s5_endpoints = []
        for label, ang in slice5_dirs:
            length_mm, pa, pb = _measure_length_along(img5, ang, ps)
            res.measurements.append(Measurement(
                label=f"Slice 5 — {label} diameter",
                value=round(length_mm, 2),
                unit="mm",
                spec=f"{nominal_d} ± {tol} mm",
                passed=abs(length_mm - nominal_d) <= tol,
            ))
            s5_endpoints.append((label, pa, pb, length_mm))

        def _draw_slice5(ax):
            colors = ["cyan", "magenta", "yellow", "lime"]
            for (label, pa, pb, L), c in zip(s5_endpoints, colors):
                ax.plot([pa[1], pb[1]], [pa[0], pb[0]], color=c, lw=1.6)
                ax.annotate(f"{L:.1f}", xy=((pa[1] + pb[1]) / 2, (pa[0] + pb[0]) / 2),
                            color=c, fontsize=8, xytext=(6, 6), textcoords="offset points")

        res.annotated_images.append((
            "Slice 5: four diameters",
            render_annotated(img5, "Slice 5 — geometric accuracy", _draw_slice5)))

        # Overall pass = all measurements that have a pass/fail verdict
        verdicts = [m.passed for m in res.measurements if m.passed is not None]
        res.passed = all(verdicts) if verdicts else None
        res.notes = (
            f"Axial diameters (slices 1 & 5) nominal {nominal_d:.0f} mm via "
            f"half-max edges through the centroid; tolerance ±{tol} mm. "
            "Superior-inferior length is measured separately on the sagittal "
            "localizer (run that analysis on a 1-image series)."
        )

        # --- Detection-quality heuristics ---
        lo, hi = spec.diameter_plausible_mm
        for m in res.measurements:
            if m.value < lo or m.value > hi:
                res.add_warning(
                    f"{m.label}: measured {m.value} mm is far outside the expected range "
                    f"({lo}–{hi} mm) — likely an edge-detection error, not a real geometric "
                    "failure. Check the overlay.",
                    severity="low",
                )
            elif abs(m.value - nominal_d) > 10:
                res.add_warning(
                    f"{m.label}: deviation from nominal ({m.value} vs {nominal_d} mm) — verify "
                    "the measurement line crosses the phantom edges cleanly in the overlay.",
                    severity="medium",
                )
    except Exception as exc:  # pragma: no cover - defensive
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
