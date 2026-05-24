"""Test 4 — Slice Position Accuracy (ACR MR QC Manual 2015 §3.4)

Geometry (validated against real Siemens Skyra ACR data)
--------------------------------------------------------
At the top-centre of slices 1 and 11 sits a pair of vertical bars (signal
voids cut into the top of the phantom), separated by a thin septum. Both
bars share a top edge (the phantom rim). When the slice is correctly
positioned the two bars descend to the same depth; a slice-position error
makes one bar longer than the other.

We measure the vertical length of the left bar and the right bar and report

    bar_difference = right_length - left_length   (mm)

Preferred target: |bar_difference| ≤ 5 mm; values greater than 7 mm fail.

Algorithm
---------
1.  Localize the phantom (centre + radius).
2.  Find the phantom rim near the top centre.
3.  For each column across the bar pair, find the dark bar run (first
    contiguous void below the rim); keep only solid bar columns.
4.  Split the bar columns into left / right halves about their midpoint.
5.  Sub-pixel locate each bar's bottom edge (half-max dark→bright crossing),
    take the median per side, and difference the two lengths.

Replaces an earlier version that measured full-height vertical column
profiles (it returned the whole phantom diameter, not the short bars).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import contiguous_runs
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


@dataclass(frozen=True)
class _BarMeasurement:
    left_len: float
    right_len: float
    bar_diff: float
    left_col: int
    right_col: int
    top: float
    left_bot: float
    right_bot: float
    cx: float
    radius_px: float
    rim: int


def _measure_one(img: np.ndarray, ps_row: float) -> _BarMeasurement:
    """Measure left/right bar lengths + overlay geometry for one slice."""
    geom = localize_phantom(img)
    cx, radius_px = geom.cx_px, geom.radius_px
    bg = float(np.median(img[img > img.max() * 0.3]))
    half = bg * 0.5

    # 1. Phantom rim near the top, sampled from a solid column beside the bars
    side_c = int(cx - 0.22 * radius_px)
    side_c = min(max(side_c, 0), img.shape[1] - 1)
    rim = int(np.argmax(img[:, side_c] > half))
    r0, r1 = rim, int(rim + 0.5 * radius_px)

    # 2. Per-column first dark run (the bar) below the rim
    col_top: dict[int, int] = {}
    col_bot: dict[int, int] = {}
    for c in range(int(cx - 15), int(cx + 16)):
        if c < 0 or c >= img.shape[1]:
            continue
        seg = img[r0:r1, c]
        runs = contiguous_runs(seg < half)
        if not runs:
            continue
        i, j = runs[0]   # first dark run below the rim (inclusive endpoints)
        if (j - i + 1) >= 12:
            col_top[c] = r0 + i
            col_bot[c] = r0 + j

    cols = sorted(col_bot)
    if len(cols) < 4:
        raise ValueError("Slice-position bar pair not found at top-centre.")
    cmid = (cols[0] + cols[-1]) / 2
    left = [c for c in cols if c < cmid]
    right = [c for c in cols if c >= cmid]
    if not left or not right:
        raise ValueError("Could not separate the left/right slice-position bars.")
    top_shared = float(np.median([col_top[c] for c in cols]))

    def _refine(colset):
        prof = img[r0:r1, colset].mean(axis=1)
        base = np.percentile(prof, 10)
        peak = np.percentile(prof, 90)
        hf = base + 0.5 * (peak - base)
        approx = int(np.median([col_bot[c] for c in colset]) - r0)
        for i in range(max(1, approx - 5), min(len(prof) - 1, approx + 6)):
            if prof[i] < hf <= prof[i + 1]:
                return r0 + i + (hf - prof[i]) / (prof[i + 1] - prof[i] + 1e-9)
        return float(r0 + approx)

    lb = _refine(left)
    rb = _refine(right)
    left_len = (lb - top_shared) * ps_row
    right_len = (rb - top_shared) * ps_row
    return _BarMeasurement(
        left_len=left_len,
        right_len=right_len,
        bar_diff=right_len - left_len,
        left_col=int(np.median(left)),
        right_col=int(np.median(right)),
        top=top_shared,
        left_bot=lb,
        right_bot=rb,
        cx=cx,
        radius_px=radius_px,
        rim=rim,
    )


def _draw_slice_position(ax, m: _BarMeasurement, acr_slice: int) -> None:
    ax.plot([m.left_col, m.left_col], [m.top, m.left_bot], color="cyan", lw=2)
    ax.plot([m.right_col, m.right_col], [m.top, m.right_bot], color="magenta", lw=2)
    ax.annotate(
        f"L={m.left_len:.1f}", (m.left_col, m.left_bot),
        color="cyan", fontsize=8, ha="right", va="top",
        xytext=(-4, 6), textcoords="offset points",
    )
    ax.annotate(
        f"R={m.right_len:.1f}", (m.right_col, m.right_bot),
        color="magenta", fontsize=8, ha="left", va="top",
        xytext=(4, 6), textcoords="offset points",
    )
    pad = int(0.55 * m.radius_px)
    ax.set_xlim(m.cx - pad, m.cx + pad)
    ax.set_ylim(m.top + 0.6 * m.radius_px, m.rim - 8)
    ax.set_title(f"Slice {acr_slice} — bar Δ = {m.bar_diff:+.2f} mm", fontsize=10)


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    spec = spec or series.spec
    preferred = spec.bar_diff_preferred_mm
    failure = spec.bar_diff_failure_mm
    res = TestResult(
        test_id="slice_position",
        test_name="Slice Position Accuracy",
        automated=True,
        passed=True,
    )
    with res.capture_failures():
        ps = series.metadata.pixel_spacing_mm
        measurement_failures: list[str] = []
        for acr_slice in (1, 11):
            slice_img = series.try_slice(acr_slice)
            if slice_img is None:
                measurement_failures.append(f"Required ACR slice {acr_slice} is not mapped.")
                res.measurements.append(Measurement(
                    label=f"Slice {acr_slice} bar-length difference",
                    value=None, unit="mm",
                    spec=f"fail if |Δ| > {failure} mm (preferred ≤ {preferred} mm)", passed=None,
                ))
                continue
            img = slice_img.astype(np.float32)
            try:
                m = _measure_one(img, ps[0])
            except ValueError as exc:
                res.measurements.append(Measurement(
                    label=f"Slice {acr_slice} bar-length difference",
                    value=None, unit="mm",
                    spec=f"fail if |Δ| > {failure} mm (preferred ≤ {preferred} mm)", passed=None,
                ))
                res.add_warning(f"Slice {acr_slice}: {exc}", severity="medium")
                measurement_failures.append(f"Slice {acr_slice}: {exc}")
                continue

            diff = m.bar_diff
            passed = abs(diff) <= failure
            res.measurements.append(Measurement(
                label=f"Slice {acr_slice} bar-length difference",
                value=round(diff, 2), unit="mm",
                spec=f"fail if |Δ| > {failure} mm (preferred ≤ {preferred} mm)", passed=passed,
            ))

            res.annotated_images.append((
                f"Slice {acr_slice} — slice position (Δ={diff:+.2f} mm)",
                render_annotated(
                    img, "",
                    lambda ax, m=m, s=acr_slice: _draw_slice_position(ax, m, s),
                ),
            ))

            # Detection-quality heuristic
            res.flag_if_implausible(
                f"Slice {acr_slice} bar-length difference",
                round(abs(diff), 2),
                plausible=(0.0, 15.0),
                unit="mm",
                context="The bar detector may have caught the wrong feature. Check the overlay.",
            )
            if preferred < abs(diff) <= failure:
                res.add_warning(
                    f"Slice {acr_slice} bar-length difference {abs(diff):.2f} mm "
                    f"exceeds the preferred ≤ {preferred:.1f} mm target but remains "
                    f"within the acceptable ≤ {failure:.1f} mm limit.",
                    severity="medium",
                )
            if acr_slice == 11 and abs(diff) > 4.0:
                res.add_warning(
                    "Slice 11 bar-length difference exceeds 4.0 mm; ACR guidance "
                    "notes this can adversely affect low-contrast detectability.",
                    severity="medium",
                )

        if measurement_failures:
            res.passed = None
            res.error = " ".join(measurement_failures)
        else:
            res.finalize_pass()
        res.notes = (
            "Left/right bar lengths measured from the shared phantom rim to each bar's "
            f"sub-pixel bottom edge. Δ = right − left (a longer left bar is negative); "
            f"preferred |Δ| ≤ {preferred:.0f} mm; "
            f"values greater than {failure:.0f} mm fail."
        )
    return res
