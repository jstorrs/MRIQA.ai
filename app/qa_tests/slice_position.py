"""Test 4 — Slice Position Accuracy (ACR MR QC Manual 2015 §3.4)

Geometry (validated against real Siemens Skyra ACR data)
--------------------------------------------------------
At the top-centre of slices 1 and 11 sits a pair of vertical bars (signal
voids cut into the top of the phantom), separated by a thin septum. Both
bars share a top edge (the phantom rim). When the slice is correctly
positioned the two bars descend to the same depth; a slice-position error
makes one bar longer than the other.

We measure the vertical length of the left bar and the right bar and report

    bar_difference = left_length - right_length   (mm)

Action limit: |bar_difference| ≤ 5 mm.

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

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.geometry import contiguous_runs
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def _measure_one(img: np.ndarray, ps_row: float):
    """Return a dict with bar lengths + geometry for one slice."""
    geom = localize_phantom(img)
    cx, R = geom.cx_px, geom.radius_px
    bg = float(np.median(img[img > img.max() * 0.3]))
    half = bg * 0.5

    # 1. Phantom rim near the top, sampled from a solid column beside the bars
    side_c = int(cx - 0.22 * R)
    side_c = min(max(side_c, 0), img.shape[1] - 1)
    rim = int(np.argmax(img[:, side_c] > half))
    r0, r1 = rim, int(rim + 0.5 * R)

    # 2. Per-column first dark run (the bar) below the rim
    col_top, col_bot = {}, {}
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
    return {
        "left_len": left_len, "right_len": right_len,
        "bar_diff": left_len - right_len,
        "left_col": int(np.median(left)), "right_col": int(np.median(right)),
        "top": top_shared, "left_bot": lb, "right_bot": rb,
        "cx": cx, "R": R, "rim": rim,
    }


def run(series: DicomSeries, *, spec: PhantomSpec | None = None) -> TestResult:
    if spec is None:
        spec = series.spec
    tol = spec.bar_diff_tolerance_mm
    res = TestResult(
        test_id="slice_position",
        test_name="Slice Position Accuracy",
        automated=True,
        passed=True,
    )
    try:
        ps = series.metadata.pixel_spacing_mm
        for acr_slice in (1, 11):
            slice_img = series.try_slice(acr_slice)
            if slice_img is None:
                continue
            img = slice_img.astype(np.float32)
            try:
                r = _measure_one(img, ps[0])
            except Exception as exc:
                res.measurements.append(Measurement(
                    label=f"Slice {acr_slice} bar-length difference",
                    value=float("nan"), unit="mm",
                    spec=f"|Δ| ≤ {tol} mm", passed=None,
                ))
                res.add_warning(f"Slice {acr_slice}: {exc}", severity="medium")
                continue

            diff = r["bar_diff"]
            passed = abs(diff) <= tol
            res.measurements.append(Measurement(
                label=f"Slice {acr_slice} bar-length difference",
                value=round(diff, 2), unit="mm",
                spec=f"|Δ| ≤ {tol} mm", passed=passed,
            ))

            def _draw(ax, r=r, acr_slice=acr_slice):
                ax.plot([r["left_col"], r["left_col"]], [r["top"], r["left_bot"]],
                        color="cyan", lw=2)
                ax.plot([r["right_col"], r["right_col"]], [r["top"], r["right_bot"]],
                        color="magenta", lw=2)
                ax.annotate(f"L={r['left_len']:.1f}", (r["left_col"], r["left_bot"]),
                            color="cyan", fontsize=8, ha="right", va="top",
                            xytext=(-4, 6), textcoords="offset points")
                ax.annotate(f"R={r['right_len']:.1f}", (r["right_col"], r["right_bot"]),
                            color="magenta", fontsize=8, ha="left", va="top",
                            xytext=(4, 6), textcoords="offset points")
                pad = int(0.55 * r["R"])
                ax.set_xlim(r["cx"] - pad, r["cx"] + pad)
                ax.set_ylim(r["top"] + 0.6 * r["R"], r["rim"] - 8)
                ax.set_title(f"Slice {acr_slice} — bar Δ = {r['bar_diff']:+.2f} mm", fontsize=10)

            res.annotated_images.append((
                f"Slice {acr_slice} — slice position (Δ={diff:+.2f} mm)",
                render_annotated(img, "", _draw)))

            # Detection-quality heuristic
            if abs(diff) > 15:
                res.add_warning(
                    f"Slice {acr_slice}: |Δ| = {abs(diff):.1f} mm is implausibly large — "
                    "the bar detector may have caught the wrong feature. Check the overlay.",
                    severity="low",
                )

        verdicts = [m.passed for m in res.measurements if m.passed is not None]
        res.passed = all(verdicts) if verdicts else None
        res.notes = (
            "Left/right bar lengths measured from the shared phantom rim to each bar's "
            f"sub-pixel bottom edge. Δ = left − right; action limit |Δ| ≤ {tol:.0f} mm."
        )
    except Exception as exc:
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
