"""Test 3 — Slice Thickness Accuracy (ACR MR QC Manual 2015 §3.3)

Geometry (validated against real Siemens Skyra ACR data)
--------------------------------------------------------
On slice 1, at the phantom centre, the slice-thickness insert appears as a
horizontal **signal void** (a dark band ~10-12 px tall) bracketed by bright
phantom above and below. Inside that void sit **two faint bright signal
ramps** — an upper ramp and a lower ramp — separated by a thin darker
septum. Each ramp is a lens-shaped bright ridge running left-to-right.

The ACR slice thickness is computed from the horizontal FWHM of each ramp:

    slice_thickness = 0.2 * (top * bottom) / (top + bottom)

where ``top`` and ``bottom`` are the ramp FWHM lengths in mm. The harmonic
mean makes the result robust to small slice offsets (one ramp lengthens as
the other shortens). Nominal 5.0 mm, action limit ±0.7 mm.

Algorithm
---------
1.  Localize the phantom (centre + radius).
2.  Find the slice-thickness void band: the contiguous run of low-signal
    rows nearest the phantom centre (bracketed by bright phantom).
3.  Find the septum: the darker row between the two bright ramp peaks.
4.  For the upper and lower ramp, build a horizontal profile (rows averaged),
    measure FWHM at half-max above the void baseline.
5.  Apply the ACR formula and run sanity checks.

This replaces an earlier version that locked onto the wrong features (the
bright phantom edges / small end bars) and produced implausible values.
"""

from __future__ import annotations

import numpy as np

from ..io_dicom.dicom_loader import DicomSeries
from ..utils.phantom import localize_phantom
from ..utils.viz import render_annotated
from .base import Measurement, TestResult

NOMINAL_THICKNESS_MM = 5.0
THICKNESS_TOLERANCE_MM = 0.7


def _smooth(p: np.ndarray, n: int = 3) -> np.ndarray:
    return np.convolve(p.astype(float), np.ones(n) / n, mode="same")


def _contiguous_runs(mask: np.ndarray):
    runs = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def _fwhm_with_pos(profile: np.ndarray, x0: int):
    """FWHM (px) of a bright ramp over a void baseline, plus the sub-pixel
    left/right column positions for annotation."""
    p = _smooth(profile, 3)
    base = np.percentile(p, 5)        # void floor
    peak = p.max()
    if peak - base < 1e-6:
        return 0.0, None, None
    half = base + 0.5 * (peak - base)
    above = np.where(p >= half)[0]
    if above.size < 2:
        return 0.0, None, None
    l, r = above[0], above[-1]
    lf = l - 1 + (half - p[l - 1]) / (p[l] - p[l - 1] + 1e-9) if l > 0 else float(l)
    rf = r + (half - p[r]) / (p[r + 1] - p[r] + 1e-9) if r < len(p) - 1 else float(r)
    return rf - lf, x0 + lf, x0 + rf


def run(series: DicomSeries) -> TestResult:
    res = TestResult(
        test_id="slice_thickness",
        test_name="Slice Thickness Accuracy",
        automated=True,
        passed=True,
    )
    try:
        img = series.slice(1).astype(np.float32)
        ps = series.metadata.pixel_spacing_mm   # (row, col)
        geom = localize_phantom(img)
        cx, cy, R = geom.cx_px, geom.cy_px, geom.radius_px

        # --- 1. Find the slice-thickness void band near the phantom centre ---
        c_lo, c_hi = int(cx - 0.45 * R), int(cx + 0.45 * R)
        rprof = img[:, c_lo:c_hi].mean(axis=1)
        bg = float(np.median(rprof[rprof > 0]))
        void_mask = rprof < bg * 0.4
        runs = _contiguous_runs(void_mask)
        cand = [(s, e) for (s, e) in runs if 3 <= (e - s + 1) <= 20 and s <= cy <= e]
        if not cand:
            cand = sorted(
                [(s, e) for (s, e) in runs if 3 <= (e - s + 1) <= 20],
                key=lambda rr: abs((rr[0] + rr[1]) / 2 - cy),
            )
        if not cand:
            raise ValueError("Slice-thickness void band not found near phantom centre.")
        band_top, band_bot = cand[0]

        # --- 2. Find the septum between the two ramp peaks ---
        cc_lo, cc_hi = int(cx - 0.25 * R), int(cx + 0.25 * R)
        bright = _smooth(img[band_top:band_bot + 1, cc_lo:cc_hi].mean(axis=1), 3)
        mid = len(bright) // 2
        up_peak = int(np.argmax(bright[: mid + 1]))
        lo_peak = mid + int(np.argmax(bright[mid:]))
        if lo_peak <= up_peak:
            lo_peak = min(len(bright) - 1, up_peak + 1)
        septum = band_top + up_peak + int(np.argmin(bright[up_peak:lo_peak + 1]))
        septum = min(max(septum, band_top + 1), band_bot - 1)

        # --- 3. Measure each ramp's horizontal FWHM ---
        x0, x1 = int(cx - 0.55 * R), int(cx + 0.55 * R)
        up_prof = img[band_top:septum, x0:x1].mean(axis=0)
        lo_prof = img[septum + 1:band_bot + 1, x0:x1].mean(axis=0)
        fu, u_l, u_r = _fwhm_with_pos(up_prof, x0)
        fl, l_l, l_r = _fwhm_with_pos(lo_prof, x0)
        top_mm = fu * ps[1]
        bot_mm = fl * ps[1]
        if top_mm + bot_mm < 1e-6:
            raise ValueError("Failed to fit ramp FWHM in the slice-thickness insert.")

        thickness_mm = 0.2 * (top_mm * bot_mm) / (top_mm + bot_mm)

        m = Measurement(
            label="Measured slice thickness",
            value=round(thickness_mm, 2),
            unit="mm",
            spec=f"{NOMINAL_THICKNESS_MM} ± {THICKNESS_TOLERANCE_MM} mm",
            passed=abs(thickness_mm - NOMINAL_THICKNESS_MM) <= THICKNESS_TOLERANCE_MM,
        )
        res.measurements.append(m)
        res.measurements.append(Measurement("Top ramp FWHM", round(top_mm, 2), "mm"))
        res.measurements.append(Measurement("Bottom ramp FWHM", round(bot_mm, 2), "mm"))
        res.passed = bool(m.passed)
        res.notes = (
            "Slice thickness = 0.2 × top × bot / (top + bot). FWHM of the two bright "
            "signal ramps inside the slice-thickness void band, measured at half-max "
            "above the void baseline."
        )

        up_row = (band_top + septum) // 2
        lo_row = (septum + 1 + band_bot) // 2

        def _draw(ax):
            if u_l is not None:
                ax.plot([u_l, u_r], [up_row, up_row], color="cyan", lw=2)
                ax.annotate(f"top {top_mm:.1f} mm", (u_r, up_row), color="cyan",
                            fontsize=8, va="center", xytext=(5, -6),
                            textcoords="offset points")
            if l_l is not None:
                ax.plot([l_l, l_r], [lo_row, lo_row], color="magenta", lw=2)
                ax.annotate(f"bot {bot_mm:.1f} mm", (l_r, lo_row), color="magenta",
                            fontsize=8, va="center", xytext=(5, 6),
                            textcoords="offset points")
            ax.set_title(f"Slice 1 — slice thickness {thickness_mm:.2f} mm", fontsize=10)

        # Zoom the annotated view onto the insert so the ramps are visible
        def _draw_zoom(ax):
            _draw(ax)
            pad = int(0.6 * R)
            ax.set_xlim(cx - pad, cx + pad)
            ax.set_ylim(band_bot + 12, band_top - 12)  # inverted y (image coords)

        res.annotated_images.append((
            f"Slice 1 — slice-thickness ramps (={thickness_mm:.2f} mm)",
            render_annotated(img, "", _draw_zoom)))

        # --- 4. Detection-quality heuristics ---
        if thickness_mm < 1.0 or thickness_mm > 15.0:
            res.add_warning(
                f"Measured thickness {thickness_mm:.2f} mm is implausible — the ramp "
                "detector may have failed. Check the overlay.",
                severity="low",
            )
        if top_mm < 10 or bot_mm < 10:
            res.add_warning(
                f"A ramp FWHM is very short (top={top_mm:.1f} mm, bot={bot_mm:.1f} mm) — "
                "low SNR or mis-detected ramp. Check the overlay.",
                severity="medium",
            )
        if top_mm and bot_mm:
            asym = abs(top_mm - bot_mm) / max(top_mm, bot_mm)
            if asym > 0.4:
                res.add_warning(
                    f"Top and bottom ramp FWHM differ by {asym*100:.0f}% — the slice may be "
                    "offset from the ramp crossing, or a ramp was mis-detected.",
                    severity="medium",
                )
    except Exception as exc:
        res.passed = None
        res.error = f"{type(exc).__name__}: {exc}"
    return res
