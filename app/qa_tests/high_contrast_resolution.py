"""Test 2 — High-Contrast Spatial Resolution (ACR MR QC Manual 2015 §3.2)

This is a *user-confirmation* test in the MVP.

Procedure
---------
On slice 1, the upper-left (UL) and lower-right (LR) corners of the
phantom contain three sets of hole arrays at 1.1 mm, 1.0 mm and 0.9 mm.
The technologist visually decides the smallest array in which all four
rows of holes are resolvable, separately for UL and LR.

Action limit: at the standard ACR FOV (250 mm) and 256 matrix, the
1.0 mm row must be resolvable in both UL and LR. Stricter sites may
require 0.9 mm.

In the MVP the app shows a zoomed view of each insert and asks the user
to select the smallest resolvable row. The user's choice becomes the
test result.
"""

from __future__ import annotations

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.phantom import localize_phantom
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def crop_resolution_insert(image: np.ndarray, geom, corner: str) -> np.ndarray:
    """Return a zoomed crop centered on the UL or LR resolution insert.

    The inserts sit just inside the upper-left and lower-right of the
    phantom, roughly at radius 0.65*r along the diagonals.
    """
    H, W = image.shape
    cy, cx, r = geom.cy_px, geom.cx_px, geom.radius_px
    half = int(0.35 * r)
    if corner.lower() == "ul":
        yc = int(cy - 0.60 * r)
        xc = int(cx - 0.60 * r)
    else:  # 'lr'
        yc = int(cy + 0.60 * r)
        xc = int(cx + 0.60 * r)
    y0, y1 = max(0, yc - half), min(H, yc + half)
    x0, x1 = max(0, xc - half), min(W, xc + half)
    return image[y0:y1, x0:x1], (y0, y1, x0, x1)


def run(series: DicomSeries, *, user_input: dict | None = None) -> TestResult:
    """`user_input` is a dict like {'UL': 1.0, 'LR': 0.9, 'spec': 1.0}.

    If `user_input` is None the test runs in "needs review" mode and
    returns the zoomed insert images for the technologist to inspect.
    """
    res = TestResult(
        test_id="high_contrast_resolution",
        test_name="High-Contrast Spatial Resolution",
        automated=False,
        passed=None,
    )
    try:
        img = series.slice(1).astype(np.float32)
        geom = localize_phantom(img)
        for corner in ("UL", "LR"):
            crop, _ = crop_resolution_insert(img, geom, corner)
            def _draw(ax, corner=corner):
                ax.set_title(f"Slice 1 — {corner} hole arrays (zoom)", fontsize=10)
            res.annotated_images.append((
                f"Slice 1 — {corner} hole arrays",
                render_annotated(crop, "", _draw)))

        if user_input:
            spec = float(user_input.get("spec", 1.0))
            ul = user_input.get("UL")
            lr = user_input.get("LR")
            def _mark(label, val):
                if val is None:
                    res.measurements.append(Measurement(label, value=float("nan"), unit="mm"))
                    return None
                passed = float(val) <= spec  # smaller resolvable spacing is better
                res.measurements.append(Measurement(
                    label=label, value=float(val), unit="mm",
                    spec=f"≤ {spec:.1f} mm", passed=passed,
                ))
                return passed
            p_ul = _mark("UL smallest resolvable", ul)
            p_lr = _mark("LR smallest resolvable", lr)
            if p_ul is not None and p_lr is not None:
                res.passed = bool(p_ul and p_lr)
        else:
            res.notes = "Open the test page in the UI and select the smallest row resolvable in UL and LR."
    except Exception as exc:
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
