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
from skimage.filters import threshold_otsu
from skimage.measure import label, regionprops

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def _draw_lcd_title(ax, acr: int) -> None:
    ax.set_title(
        f"Slice {acr} — low-contrast spokes (count complete spokes)",
        fontsize=9,
    )


def _lcd_chamber_center(img: np.ndarray, phantom_mask: np.ndarray) -> tuple[float, float] | None:
    """Centroid of the LCD insert chamber on an axial slice.

    The phantom mask centroid is not always a good crop target — on the
    ACR Large/Medium phantoms there is enough bright asymmetric structure
    (fiducials, grid markers) to shift the area centroid above the actual
    LCD pattern. Inside the phantom mask the LCD insert is the largest
    dark connected component; its centroid is the right anchor for the
    spokes view.
    """
    try:
        t = threshold_otsu(img)
    except ValueError:
        # threshold_otsu raises ValueError on constant images.
        return None
    dark_interior = (img < t) & phantom_mask
    lbl = label(dark_interior)
    if lbl.max() == 0:
        return None
    biggest = max(regionprops(lbl), key=lambda r: r.area)
    cy, cx = biggest.centroid
    return float(cy), float(cx)


def run(
    series: DicomSeries,
    *,
    spec: PhantomSpec | None = None,
    user_input: dict | None = None,
) -> TestResult:
    """`user_input` is a dict {acr_slice_role: spokes_seen, ...}."""
    spec = spec or series.spec
    lcd_slices = spec.lcd_slices
    res = TestResult(
        test_id="low_contrast_detectability",
        test_name="Low-Contrast Object Detectability",
        automated=False,
        passed=None,
    )
    with res.capture_failures():
        for acr in lcd_slices:
            slice_img = series.try_slice(acr, spec_fallback=True)
            if slice_img is None:
                continue
            img = slice_img.astype(np.float32)
            geom = localize_phantom(img)
            # Zoom onto the central low-contrast disk pattern. The spoke
            # insert is the same physical size in the Large and Medium
            # phantoms, so anchor the crop to a fixed mm half-width from the
            # spec rather than scaling with phantom radius. Center on the LCD
            # chamber itself (largest dark region inside the phantom) rather
            # than the phantom centroid — asymmetric bright structure on the
            # phantom (fiducials, grid markers) pulls the area centroid above
            # the actual LCD pattern.
            center = _lcd_chamber_center(img, geom.mask)
            if center is None:
                cy_c, cx_c = geom.cy_px, geom.cx_px
            else:
                cy_c, cx_c = center
            H, W = img.shape
            ps = series.metadata.pixel_spacing_mm  # (row, col)
            half_px_y = max(1, int(round(spec.lcd_insert_half_width_mm / ps[0])))
            half_px_x = max(1, int(round(spec.lcd_insert_half_width_mm / ps[1])))
            y0 = max(0, int(cy_c) - half_px_y)
            y1 = min(H, int(cy_c) + half_px_y)
            x0 = max(0, int(cx_c) - half_px_x)
            x1 = min(W, int(cx_c) + half_px_x)
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
                res.add_warning(
                    f"Slice {acr}: LCD chamber crop has no positive signal — "
                    "the chamber may have been mis-localized. Check the overlay.",
                    severity="medium",
                )

            res.annotated_images.append((
                f"Slice {acr} — LCD pattern",
                render_annotated(
                    crop, "",
                    lambda ax, acr=acr: _draw_lcd_title(ax, acr),
                    wl=wl, ww=ww,
                ),
            ))

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
            if is_3t:
                threshold = spec.lcd_threshold_3t
            elif series.metadata.sequence == "T2":
                threshold = spec.lcd_threshold_lowfield_t2
            else:
                threshold = spec.lcd_threshold_lowfield_t1
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
    return res
