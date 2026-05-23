"""Test 5 — Image Intensity Uniformity / PIU
(ACR Large and Medium Phantom Test Guidance, Oct 2022, § 5)

Procedure
---------
* Use slice 7 of the ACR axial series.
* Define a large ROI centered in the phantom (200 cm² for Large,
  160 cm² for Medium — see ``spec.piu_large_roi_area_cm2``).
* Slide a small ROI (~1 cm²) inside the large ROI. Find the small ROI
  with the highest mean signal and the small ROI with the lowest mean
  signal.
* PIU = 100 × (1 − (high − low) / (high + low)).
* Action limits (Large phantom, per § 5.4 / Table 4):
    - ≥ 87.5 % at < 3 T
    - ≥ 82.0 % at 3 T   (lower because of dielectric/conductivity effects)
  Medium phantom is tighter (≥ 90 % at < 3 T, ≥ 85 % at 3 T).

Implementation
--------------
We rasterize a candidate-centers grid inside the large ROI and compute
the small-ROI mean using `scipy.ndimage.uniform_filter`, which gives the
mean of every possible small ROI in one pass. Then we mask to candidate
centers and take min/max.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import uniform_filter

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import circular_roi_mask
from ..utils.phantom import localize_phantom, phantom_quality_warnings
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def _radius_for_area_px(area_cm2: float, pixel_spacing_mm) -> float:
    area_mm2 = area_cm2 * 100.0  # cm² -> mm²
    px_area_mm2 = pixel_spacing_mm[0] * pixel_spacing_mm[1]
    radius_px = math.sqrt(area_mm2 / px_area_mm2 / math.pi)
    return radius_px


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    spec = spec or series.spec
    large_area = spec.piu_large_roi_area_cm2
    small_area = spec.piu_small_roi_area_cm2
    threshold_3t = spec.piu_threshold_3t_percent
    threshold_lo = spec.piu_threshold_lowfield_percent
    res = TestResult(
        test_id="uniformity",
        test_name="Image Intensity Uniformity (PIU)",
        automated=True,
        passed=True,
    )
    with res.capture_failures():
        img = series.slice(7).astype(np.float32)
        ps = series.metadata.pixel_spacing_mm
        geom = localize_phantom(img)
        for w in phantom_quality_warnings(geom, ps, spec):
            res.add_warning(w, severity="medium")

        r_large = _radius_for_area_px(large_area, ps)
        # Don't let the large ROI exceed the phantom interior
        r_large = min(r_large, geom.radius_px * 0.85)
        r_small = _radius_for_area_px(small_area, ps)

        large_mask = circular_roi_mask(img.shape, geom.cy_px, geom.cx_px, r_large)
        # The ACR procedure requires the small 1 cm² ROI to be placed *inside*
        # the large ROI (§ 5 steps 3, 4, 6). Constrain candidate centers to a
        # tighter disk so the small ROI disk fits fully within the large ROI
        # boundary — half-pixel-pad so the rasterized circle stays inside.
        candidate_mask = circular_roi_mask(
            img.shape, geom.cy_px, geom.cx_px, max(1.0, r_large - r_small - 0.5),
        )
        # Mean of the small ROI at every center pixel: a uniform circular filter.
        # We approximate the circular small-ROI mean with a square box of equal area.
        # This is the standard interpretation used by many ACR analysers.
        # Ceil rather than round so the box doesn't shrink below the requested
        # small-ROI area when 2*r_small has a fractional part.
        box_size = max(3, int(math.ceil(2 * r_small)))
        small_mean = uniform_filter(img, size=box_size)

        # --- Exclude air / voids (e.g. the phantom's top air bubble or any
        #     structural void) so they don't dominate the "low" ROI. We measure
        #     the uniformity of phantom *material*, not air. A small ROI is only
        #     a valid candidate if it lies entirely on phantom signal.
        med = float(np.median(img[large_mask]))
        air = (img < 0.5 * med).astype(np.float32)
        air_frac = uniform_filter(air, size=box_size)   # fraction of small ROI that is air

        # Candidate centers: inside the (tightened) large ROI, away from the
        # image edge, no air overlap.
        margin = int(math.ceil(r_small))
        ys, xs = np.where(candidate_mask)
        valid = (ys >= margin) & (ys < img.shape[0] - margin) & (xs >= margin) & (xs < img.shape[1] - margin)
        ys, xs = ys[valid], xs[valid]
        af = air_frac[ys, xs]
        clean = af <= 1e-6
        n_excluded = int((~clean).sum())
        if clean.sum() >= 10:           # keep only air-free candidates if enough remain
            ys, xs = ys[clean], xs[clean]
        if n_excluded > 20:
            res.add_warning(
                f"Excluded {n_excluded} ROI position(s) overlapping air/void (e.g. the "
                "phantom's top air bubble) from the uniformity search. Uniformity is "
                "measured on phantom material only.",
                severity="medium" if n_excluded > 800 else "high",
            )

        means = small_mean[ys, xs]
        i_max = int(np.argmax(means))
        i_min = int(np.argmin(means))
        s_high = float(means[i_max])
        s_low = float(means[i_min])
        cy_high, cx_high = int(ys[i_max]), int(xs[i_max])
        cy_low, cx_low = int(ys[i_min]), int(xs[i_min])

        piu = 100.0 * (1.0 - (s_high - s_low) / (s_high + s_low + 1e-9))

        is_3t = series.metadata.field_strength_t >= 3.0 - 0.05
        threshold = threshold_3t if is_3t else threshold_lo

        m = Measurement(
            label="PIU",
            value=round(piu, 2),
            unit="%",
            spec=f"≥ {threshold:.1f} % (B0 = {series.metadata.field_strength_t:.1f} T)",
            passed=piu >= threshold,
        )
        res.measurements.append(m)
        res.passed = bool(m.passed)
        res.notes = (
            f"Large ROI area ≈ {large_area:.0f} cm² (radius={r_large*((ps[0]+ps[1])/2):.1f} mm). "
            f"Small ROI ≈ {small_area:.0f} cm². High mean = {s_high:.1f}, Low mean = {s_low:.1f}."
        )

        # --- Detection-quality heuristics ---
        if piu < 50 or piu > 100:
            res.add_warning(
                f"PIU = {piu:.1f}% is outside the plausible range (50–100%); the small-ROI "
                "search may have included background or air voxels. Check the overlay.",
                severity="low",
            )
        if s_low <= 0:
            res.add_warning(
                "Lowest small-ROI mean is zero or negative — the ROI may have landed outside "
                "the phantom.",
                severity="low",
            )

        # ----- Annotate -----
        def _draw(ax):
            from matplotlib.patches import Circle
            # Large ROI
            ax.add_patch(Circle((geom.cx_px, geom.cy_px), r_large, fill=False, edgecolor="cyan", lw=1.5))
            # Small high (red) and low (blue) ROIs
            ax.add_patch(Circle((cx_high, cy_high), r_small, fill=False, edgecolor="red", lw=1.6))
            ax.annotate(f"max={s_high:.0f}", (cx_high, cy_high), color="red", fontsize=8,
                        xytext=(8, -8), textcoords="offset points")
            ax.add_patch(Circle((cx_low, cy_low), r_small, fill=False, edgecolor="blue", lw=1.6))
            ax.annotate(f"min={s_low:.0f}", (cx_low, cy_low), color="blue", fontsize=8,
                        xytext=(8, 8), textcoords="offset points")
            ax.set_title(f"Slice 7 — PIU = {piu:.2f} %", fontsize=10)

        res.annotated_images.append((f"Slice 7 — PIU={piu:.2f}%",
                                     render_annotated(img, "", _draw)))
    return res
