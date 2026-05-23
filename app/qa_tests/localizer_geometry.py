"""Sagittal-localizer geometric accuracy (ACR MR QC Manual 2015 §3.1).

The ACR geometric-accuracy procedure measures the phantom's
**superior-inferior length** on the sagittal localizer. The S-I axis only
lies in the image plane on the sagittal scout, so this measurement cannot
be obtained from any axial slice — it is a standalone analysis on a
single-image series.

Axial in-plane diameters (slices 1 & 5) are handled separately by
``app.qa_tests.geometric_accuracy``.
"""

from __future__ import annotations

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import phantom_chord_endpoints
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def _measure_si_length(localizer: DicomSeries):
    """Return (length_mm, image, bbox, line) for the phantom S-I length.

    bbox is (y0, y1, x0, x1) of the phantom mask. `line` is the two
    endpoint pixel coords ((y, x), (y, x)) drawn through the phantom
    along the S-I axis.
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
        except (TypeError, ValueError, IndexError):
            pass

    ys, xs = np.where(geom.mask)
    if ys.size == 0:
        raise ValueError("Phantom not found on localizer.")
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    H, W = img.shape
    cy_c, cx_c = geom.cy_px, geom.cx_px

    # Measure along a chord through the phantom centroid using sub-pixel
    # half-max edges (same approach as axial geometric_accuracy), rather
    # than the mask bounding box. The mask extents are sensitive to single
    # noisy edge pixels; the half-max chord matches the in-plane diameters.
    if col_is_si:
        L = H * 1.2
        p0 = (cy_c - L / 2, cx_c)
        p1 = (cy_c + L / 2, cx_c)
        (y_in, x_in), (y_out, x_out) = phantom_chord_endpoints(img, p0, p1)
        length_mm = abs(y_out - y_in) * ps[0]
    else:
        L = W * 1.2
        p0 = (cy_c, cx_c - L / 2)
        p1 = (cy_c, cx_c + L / 2)
        (y_in, x_in), (y_out, x_out) = phantom_chord_endpoints(img, p0, p1)
        length_mm = abs(x_out - x_in) * ps[1]
    line = ((y_in, x_in), (y_out, x_out))

    return length_mm, img, (y0, y1, x0, x1), line


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    """Run the sagittal-localizer S-I length check on a 1-image series."""
    spec = spec or series.spec
    nominal_si = spec.si_length_mm
    tol = spec.length_tolerance_mm
    res = TestResult(
        test_id="localizer_geometric_accuracy",
        test_name="Geometric Accuracy — Sagittal Localizer",
        automated=True,
        passed=True,
    )
    with res.capture_failures():
        si_len, img, _, line = _measure_si_length(series)
        passed = abs(si_len - nominal_si) <= tol
        res.measurements.append(Measurement(
            label="Superior-inferior length",
            value=round(si_len, 2),
            unit="mm",
            spec=f"{nominal_si} ± {tol} mm",
            passed=passed,
        ))

        def _draw(ax, line=line, si_len=si_len):
            (ya, xa), (yb, xb) = line
            ax.plot([xa, xb], [ya, yb], color="red", lw=2)
            ax.annotate(f"{si_len:.1f} mm",
                        xy=((xa + xb) / 2, (ya + yb) / 2),
                        color="red", fontsize=9,
                        xytext=(8, 0), textcoords="offset points")

        res.annotated_images.append((
            f"Sagittal localizer: S-I length ({nominal_si:.0f} mm nominal)",
            render_annotated(img, "Sagittal localizer — S-I length", _draw)))

        res.passed = passed
        res.notes = (
            f"S-I length measured on the sagittal localizer (nominal "
            f"{nominal_si:.0f} mm, tolerance ±{tol} mm). "
            "Edges via phantom mask extents; the S-I axis is taken from the "
            "DICOM ImageOrientationPatient tag."
        )

        res.flag_if_implausible(
            "Superior-inferior length",
            round(si_len, 2),
            plausible=spec.si_length_plausible_mm,
            unit="mm",
            nominal=nominal_si,
            big_deviation=10,
            context="Check the overlay.",
        )
    return res
