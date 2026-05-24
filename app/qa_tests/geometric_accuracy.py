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
from typing import Callable

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import phantom_chord_endpoints
from ..utils.phantom import PhantomGeometry, localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


_SLICE1_DIRS = [("Horizontal (L-R)", 0.0), ("Vertical (A-P)", 90.0)]
_SLICE5_DIRS = [
    ("Horizontal (L-R)", 0.0),
    ("Vertical (A-P)",   90.0),
    ("Diagonal 45°",     45.0),
    ("Diagonal 135°",    135.0),
]
_SLICE1_COLORS = ["cyan", "magenta"]
_SLICE5_COLORS = ["cyan", "magenta", "yellow", "lime"]


def _measure_length_along(
    image: np.ndarray,
    geom: PhantomGeometry,
    angle_deg: float,
    pixel_spacing_mm,
) -> tuple[float, tuple, tuple]:
    """Return (length_mm, p_entry_yx, p_exit_yx) for a chord through the
    phantom center at the given angle."""
    cy, cx = geom.cy_px, geom.cx_px

    L = max(image.shape) * 1.2
    a = math.radians(angle_deg)
    dy = math.sin(a)
    dx = math.cos(a)
    p0 = (cy - L / 2 * dy, cx - L / 2 * dx)
    p1 = (cy + L / 2 * dy, cx + L / 2 * dx)

    (y_in, x_in), (y_out, x_out) = phantom_chord_endpoints(image, p0, p1)

    dy_mm = (y_out - y_in) * pixel_spacing_mm[0]
    dx_mm = (x_out - x_in) * pixel_spacing_mm[1]
    length_mm = math.hypot(dy_mm, dx_mm)
    return length_mm, (y_in, x_in), (y_out, x_out)


def _measure_slice_diameters(
    img: np.ndarray,
    ps: tuple[float, float],
    dirs: list[tuple[str, float]],
    slice_label: str,
    nominal_d: float,
    tol: float,
    line_width: float,
) -> tuple[list[Measurement], Callable]:
    """Measure each requested diameter on one slice and return the
    measurements plus a drawing callback for the annotated overlay."""
    geom = localize_phantom(img)
    endpoints: list[tuple[str, tuple, tuple, float]] = []
    measurements: list[Measurement] = []
    for label, ang in dirs:
        length_mm, pa, pb = _measure_length_along(img, geom, ang, ps)
        measurements.append(Measurement(
            label=f"{slice_label} — {label} diameter",
            value=round(length_mm, 2),
            unit="mm",
            spec=f"{nominal_d} ± {tol} mm",
            passed=abs(length_mm - nominal_d) <= tol,
        ))
        endpoints.append((label, pa, pb, length_mm))

    colors = _SLICE5_COLORS if len(dirs) > 2 else _SLICE1_COLORS

    def _draw(ax):
        for (_label, pa, pb, L), c in zip(endpoints, colors):
            ax.plot([pa[1], pb[1]], [pa[0], pb[0]], color=c, lw=line_width)
            ax.annotate(
                f"{L:.1f}",
                xy=((pa[1] + pb[1]) / 2, (pa[0] + pb[0]) / 2),
                color=c, fontsize=8, xytext=(6, 6), textcoords="offset points",
            )

    return measurements, _draw


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    spec = spec or series.spec
    nominal_d = spec.diameter_mm
    tol = spec.length_tolerance_mm
    res = TestResult(
        test_id="geometric_accuracy",
        test_name="Geometric Accuracy",
        automated=True,
        passed=True,
    )
    with res.capture_failures():
        ps = series.metadata.pixel_spacing_mm

        for acr_slice, dirs, line_width, caption in (
            (1, _SLICE1_DIRS, 1.8, "Slice 1: horizontal & vertical diameters"),
            (5, _SLICE5_DIRS, 1.6, "Slice 5: four diameters"),
        ):
            img = series.slice(acr_slice)
            measurements, draw = _measure_slice_diameters(
                img, ps, dirs, f"Slice {acr_slice}", nominal_d, tol, line_width,
            )
            res.measurements.extend(measurements)
            res.annotated_images.append((
                caption,
                render_annotated(img, f"Slice {acr_slice} — geometric accuracy", draw),
            ))

        res.finalize_pass()
        res.notes = (
            f"Axial diameters (slices 1 & 5) nominal {nominal_d:.0f} mm via "
            f"half-max edges through the centroid; tolerance ±{tol} mm. "
            "Superior-inferior length is measured separately on the sagittal "
            "localizer (run that analysis on a 1-image series)."
        )

        for m in res.measurements:
            res.flag_if_implausible(
                m.label,
                m.value,
                plausible=spec.diameter_plausible_mm,
                unit="mm",
                nominal=nominal_d,
                big_deviation=10,
                context="Check the overlay.",
            )
    return res
