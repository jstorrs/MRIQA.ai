"""Test 7 — Low-Contrast Object Detectability / LCD
(ACR Large and Medium Phantom Test Guidance, Oct 2022, § 7)

User-confirmation test.

Procedure
---------
Slices 8, 9, 10, 11 each contain a low-contrast disk pattern (10 spokes,
each spoke three disks of decreasing contrast). Per slice the disk
contrasts are 1.4 %, 2.5 %, 3.6 %, 5.1 % respectively, so slice 11
saturates first. The technologist counts the number of *complete*
spokes visible on each slice; the test result is the **sum** across all
four slices.

Action limits (per § Table 5), applied to the total spoke count:
    - 3 T:        ≥ 37 (both ACR-T1 and ACR-T2)
    - 1.5–<3 T:  ACR-T1 ≥ 30, ACR-T2 ≥ 25 (this engine uses the T1 value)
    - < 1.5 T:    ≥ 7

The limits are identical for Large and Medium phantoms.
"""

from __future__ import annotations

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def run(
    series: DicomSeries,
    *,
    spec: PhantomSpec | None = None,
    user_input: dict | None = None,
) -> TestResult:
    """`user_input` is a dict {acr_slice_role: spokes_seen, ...}."""
    if spec is None:
        spec = series.spec
    lcd_slices = spec.lcd_slices
    res = TestResult(
        test_id="low_contrast_detectability",
        test_name="Low-Contrast Object Detectability",
        automated=False,
        passed=None,
    )
    try:
        for acr in lcd_slices:
            if acr not in series.acr_slice_map:
                continue
            img = series.slice(acr).astype(np.float32)
            geom = localize_phantom(img)
            # Zoom onto the central low-contrast disk pattern (the spokes occupy
            # roughly the central 0.7R) so the faint disks are easier to count.
            H, W = img.shape
            f = 0.78
            y0 = max(0, int(geom.cy_px - geom.radius_px * f))
            y1 = min(H, int(geom.cy_px + geom.radius_px * f))
            x0 = max(0, int(geom.cx_px - geom.radius_px * f))
            x1 = min(W, int(geom.cx_px + geom.radius_px * f))
            crop = img[y0:y1, x0:x1]

            # A tighter contrast window makes the low-contrast spokes more visible.
            inner = crop[crop > crop.max() * 0.2]
            if inner.size:
                lo = float(np.percentile(inner, 25))
                hi = float(np.percentile(inner, 99.5))
                wl = (lo + hi) / 2.0
                ww = max(1.0, (hi - lo) * 1.1)
            else:
                wl = ww = None

            def _draw(ax, acr=acr):
                ax.set_title(f"Slice {acr} — low-contrast spokes (count complete spokes)",
                             fontsize=9)

            res.annotated_images.append((
                f"Slice {acr} — LCD pattern",
                render_annotated(crop, "", _draw, wl=wl, ww=ww)))

        if user_input:
            total = 0
            for acr in lcd_slices:
                v = int(user_input.get(acr, 0) or 0)
                total += v
                res.measurements.append(Measurement(
                    label=f"Slice {acr} spokes seen",
                    value=float(v),
                    unit="spokes",
                ))
            is_3t = series.metadata.field_strength_t >= 3.0 - 0.05
            threshold = spec.lcd_threshold_3t if is_3t else spec.lcd_threshold_lowfield
            slice_range = f"{lcd_slices[0]}–{lcd_slices[-1]}"
            res.measurements.append(Measurement(
                label=f"Total spokes (slices {slice_range})",
                value=float(total),
                unit="spokes",
                spec=f"≥ {threshold}",
                passed=total >= threshold,
            ))
            res.passed = total >= threshold
        else:
            res.notes = "Count complete spokes on each slice and enter values in the UI."
    except Exception as exc:
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
