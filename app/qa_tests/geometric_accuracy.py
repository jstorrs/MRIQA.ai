"""Test 1 — Geometric Accuracy (ACR MR QC Manual 2015 §3.1)

Procedure
---------
The ACR geometric-accuracy test measures the phantom in two planes:

* **Sagittal localizer** — the superior-inferior *length* of the phantom,
  nominal **148 mm**. This can ONLY be measured where the S-I axis lies in
  the image plane (i.e. the sagittal localizer), never on an axial slice.
* **Axial slice 5** — four in-plane *diameters* (horizontal, vertical, and
  the two 45°/135° diagonals), nominal **190 mm** each.
* **Axial slice 1** — two in-plane diameters (horizontal, vertical),
  nominal **190 mm**.

Action limit: each measured length within ±2 mm of nominal.

Implementation
--------------
We localize the phantom and, for each requested orientation, draw a chord
through the centroid, sample with bilinear interpolation, find the
half-max crossings, and convert pixels → mm with PixelSpacing.

The 148 mm S-I length requires the sagittal localizer. The caller may
attach it as ``series.localizer`` (a DicomSeries). If absent, the S-I
length is reported as "not measured — upload the localizer" rather than
being measured (incorrectly) on an axial slice.
"""

from __future__ import annotations

import math

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import find_phantom_edges_along_line
from ..utils.phantom import localize_phantom
from ..utils.viz import render_annotated
from .base import Measurement, TestResult

NOMINAL_DIAMETER_MM = 190.0     # axial in-plane diameter (slices 1 and 5)
NOMINAL_SI_LENGTH_MM = 148.0    # superior-inferior length (sagittal localizer)
TOLERANCE_MM = 2.0


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


def _measure_si_length_on_localizer(localizer: DicomSeries):
    """Measure the phantom's superior-inferior length on the sagittal localizer.

    Returns (length_mm, image, bbox) where bbox = (y0, y1, x0, x1) of the
    phantom mask, and a flag telling the caller which axis was S-I so the
    overlay can draw the right line.
    """
    img = localizer.pixel_array[0].astype(np.float32)
    geom = localize_phantom(img)
    ps = localizer.metadata.pixel_spacing_mm  # (row_spacing, col_spacing)

    # Decide which image axis corresponds to patient S-I (Z) from IOP.
    ds = localizer.datasets[0] if localizer.datasets else None
    col_is_si = True   # default: vertical (rows) is S-I, as in a standard sagittal
    if ds is not None and hasattr(ds, "ImageOrientationPatient"):
        try:
            iop = [float(v) for v in ds.ImageOrientationPatient]
            row_cos_z = abs(iop[2])    # how much the horizontal image axis follows Z
            col_cos_z = abs(iop[5])    # how much the vertical image axis follows Z
            col_is_si = col_cos_z >= row_cos_z
        except Exception:
            pass

    ys, xs = np.where(geom.mask)
    if ys.size == 0:
        raise ValueError("Phantom not found on localizer.")
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())

    if col_is_si:
        length_mm = (y1 - y0) * ps[0]
        # vertical line at the phantom's horizontal center
        cx = (x0 + x1) // 2
        line = ((y0, cx), (y1, cx))
    else:
        length_mm = (x1 - x0) * ps[1]
        cy = (y0 + y1) // 2
        line = ((cy, x0), (cy, x1))

    return length_mm, img, (y0, y1, x0, x1), line


def run(series: DicomSeries) -> TestResult:
    res = TestResult(
        test_id="geometric_accuracy",
        test_name="Geometric Accuracy",
        automated=True,
        passed=True,
    )
    try:
        ps = series.metadata.pixel_spacing_mm

        # ----- Sagittal localizer: S-I length (148 mm) -----
        localizer = getattr(series, "localizer", None)
        if localizer is not None and getattr(localizer, "pixel_array", None) is not None \
                and localizer.pixel_array.shape[0] >= 1:
            try:
                si_len, loc_img, loc_bbox, loc_line = _measure_si_length_on_localizer(localizer)
                passed_si = abs(si_len - NOMINAL_SI_LENGTH_MM) <= TOLERANCE_MM
                res.measurements.append(Measurement(
                    label="Localizer — superior-inferior length",
                    value=round(si_len, 2),
                    unit="mm",
                    spec=f"{NOMINAL_SI_LENGTH_MM} ± {TOLERANCE_MM} mm",
                    passed=passed_si,
                ))

                def _draw_loc(ax, loc_line=loc_line, si_len=si_len):
                    (ya, xa), (yb, xb) = loc_line
                    ax.plot([xa, xb], [ya, yb], color="red", lw=2)
                    ax.annotate(f"{si_len:.1f} mm",
                                xy=((xa + xb) / 2, (ya + yb) / 2),
                                color="red", fontsize=9,
                                xytext=(8, 0), textcoords="offset points")

                res.annotated_images.append((
                    "Localizer: S-I length (148 mm nominal)",
                    render_annotated(loc_img, "Sagittal localizer — S-I length", _draw_loc)))
            except Exception as exc:
                res.add_warning(
                    f"Could not measure S-I length on the localizer ({exc}). "
                    "Check that the uploaded localizer is the sagittal ACR scout.",
                    severity="medium",
                )
        else:
            res.add_warning(
                "Superior-inferior length (148 mm) was not measured: no sagittal "
                "localizer was provided. Upload the localizer series in the sidebar "
                "to measure it. The S-I length cannot be measured on an axial slice.",
                severity="medium",
            )

        # ----- Axial slice 1: two diameters (190 mm) -----
        img1 = series.slice(1)
        slice1_dirs = [("Horizontal (L-R)", 0.0), ("Vertical (A-P)", 90.0)]
        s1_endpoints = []
        for label, ang in slice1_dirs:
            length_mm, pa, pb = _measure_length_along(img1, ang, ps)
            res.measurements.append(Measurement(
                label=f"Slice 1 — {label} diameter",
                value=round(length_mm, 2),
                unit="mm",
                spec=f"{NOMINAL_DIAMETER_MM} ± {TOLERANCE_MM} mm",
                passed=abs(length_mm - NOMINAL_DIAMETER_MM) <= TOLERANCE_MM,
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

        # ----- Axial slice 5: four diameters (190 mm) -----
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
                spec=f"{NOMINAL_DIAMETER_MM} ± {TOLERANCE_MM} mm",
                passed=abs(length_mm - NOMINAL_DIAMETER_MM) <= TOLERANCE_MM,
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
            "Axial diameters (slices 1 & 5) nominal 190 mm. Superior-inferior length "
            "(148 mm) is measured on the sagittal localizer only. Lengths via half-max "
            f"edges through the centroid; tolerance ±{TOLERANCE_MM} mm."
        )

        # --- Detection-quality heuristics ---
        for m in res.measurements:
            nominal = NOMINAL_SI_LENGTH_MM if "superior-inferior" in m.label.lower() else NOMINAL_DIAMETER_MM
            lo, hi = (130, 165) if nominal == NOMINAL_SI_LENGTH_MM else (160, 220)
            if m.value < lo or m.value > hi:
                res.add_warning(
                    f"{m.label}: measured {m.value} mm is far outside the expected range "
                    f"({lo}–{hi} mm) — likely an edge-detection error, not a real geometric "
                    "failure. Check the overlay.",
                    severity="low",
                )
            elif abs(m.value - nominal) > 10:
                res.add_warning(
                    f"{m.label}: deviation from nominal ({m.value} vs {nominal} mm) — verify "
                    "the measurement line crosses the phantom edges cleanly in the overlay.",
                    severity="medium",
                )
    except Exception as exc:  # pragma: no cover - defensive
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
