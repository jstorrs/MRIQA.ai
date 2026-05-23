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
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def crop_resolution_insert(image: np.ndarray, geom, corner: str) -> np.ndarray:
    """Return a zoomed crop centered on the UL or LR resolution insert.

    The inserts sit just inside the upper-left and lower-right of the
    phantom, roughly at radius 0.65*r along the diagonals.
    """
    H, W = image.shape
    bb = _detect_resolution_bbox(image, geom)
    if bb is None:
        # Geometric fallback relative to the phantom centre
        cy, cx, r = geom.cy_px, geom.cx_px, geom.radius_px
        bb = (int(cy + 0.34 * r), int(cy + 0.58 * r),
              int(cx - 0.28 * r), int(cx + 0.52 * r))

    r0, r1, c0, c1 = bb
    h = r1 - r0
    cl = corner.lower()
    if cl == "ul":          # upper blocks (vertical-hole arrays)
        y0, y1 = r0 - 5, r0 + int(0.62 * h) + 3
    elif cl == "lr":        # lower blocks (horizontal-hole arrays)
        y0, y1 = r0 + int(0.30 * h) - 1, r1 + 6
    else:                   # 'full' — the whole insert
        y0, y1 = r0 - 5, r1 + 6
    x0, x1 = c0 - 4, c1 + 5
    y0, y1 = max(0, y0), min(H, y1)
    x0, x1 = max(0, x0), min(W, x1)
    return image[y0:y1, x0:x1], (y0, y1, x0, x1)


def _longest_true_run(mask):
    best = (0, 0, 0)
    start = None
    seq = list(mask) + [False]
    for i, v in enumerate(seq):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start > best[0]:
                best = (i - start, start, i - 1)
            start = None
    return best


def _detect_resolution_bbox(image, geom):
    """Locate the hole-array block in the lower-centre of slice 1.

    The arrays are faint mid-level signal (brighter than the dark insert
    interior, much darker than the bright phantom walls). We search a
    generous window below the phantom centre, threshold for that mid band,
    and take the densest contiguous row run. Returns (r0,r1,c0,c1) or None.
    """
    import numpy as np
    cy, cx, r = geom.cy_px, geom.cx_px, geom.radius_px
    H, W = image.shape
    r0 = max(0, int(cy + 0.20 * r)); r1 = min(H, int(cy + 0.72 * r))
    c0 = max(0, int(cx - 0.28 * r)); c1 = min(W, int(cx + 0.52 * r))
    if r1 - r0 < 6 or c1 - c0 < 20:
        return None
    win = image[r0:r1, c0:c1]
    void = np.percentile(win, 15)
    phantom = np.percentile(win, 97)
    span = phantom - void
    if span < 1e-6:
        return None
    lo = void + 0.04 * span
    hi = void + 0.35 * span
    arr = (win > lo) & (win < hi)
    rc = arr.sum(axis=1)
    L, rs, re = _longest_true_run(rc > max(3, rc.max() * 0.20))
    if L < 6:
        return None
    cc = arr[rs:re + 1].sum(axis=0)
    ci = np.where(cc > max(2, cc.max() * 0.12))[0]
    if ci.size < 2:
        return None
    ay0, ay1 = r0 + rs, r0 + re
    ax0, ax1 = c0 + int(ci[0]), c0 + int(ci[-1])
    # Plausibility for the ACR resolution block
    if not (8 <= (ay1 - ay0) <= 45 and 35 <= (ax1 - ax0) <= 95):
        return None
    return (ay0, ay1, ax0, ax1)


def run(
    series: DicomSeries,
    *,
    spec: PhantomSpec | None = None,
    user_input: dict | None = None,
) -> TestResult:
    """`user_input` is a dict like {'UL': 1.0, 'LR': 0.9, 'spec': 1.0}.

    If `user_input` is None the test runs in "needs review" mode and
    returns the zoomed insert images for the technologist to inspect.
    """
    if spec is None:
        spec = series.spec
    sizes_label = " | ".join(f"{s:.1f}" for s in spec.resolution_array_sizes_mm)
    sizes_csv = " / ".join(f"{s:.1f}" for s in spec.resolution_array_sizes_mm)
    res = TestResult(
        test_id="high_contrast_resolution",
        test_name="High-Contrast Spatial Resolution",
        automated=False,
        passed=None,
    )
    try:
        img = series.slice(1).astype(np.float32)
        geom = localize_phantom(img)

        # Full insert first (all three pairs), then the UL and LR block rows.
        full_crop, _ = crop_resolution_insert(img, geom, "full")

        def _draw_full(ax):
            ax.set_title(
                f"Slice 1 — resolution insert: {sizes_label} mm (left→right)",
                fontsize=9,
            )
        res.annotated_images.append((
            f"Slice 1 — resolution insert ({sizes_csv} mm, left→right). "
            "UL blocks = vertical holes (upper), LR blocks = horizontal holes (lower).",
            render_annotated(full_crop, "", _draw_full, figsize=(8.0, 3.0))))

        for corner, label in (("UL", "UL blocks (vertical-hole arrays)"),
                              ("LR", "LR blocks (horizontal-hole arrays)")):
            crop, _ = crop_resolution_insert(img, geom, corner)
            def _draw(ax, label=label):
                ax.set_title(f"Slice 1 — {label}", fontsize=9)
            res.annotated_images.append((
                f"Slice 1 — {label}",
                render_annotated(crop, "", _draw, figsize=(8.0, 2.4))))

        if user_input:
            threshold = float(user_input.get("spec", spec.resolution_pass_threshold_mm))
            ul = user_input.get("UL")
            lr = user_input.get("LR")
            def _mark(label, val):
                if val is None:
                    res.measurements.append(Measurement(label, value=float("nan"), unit="mm"))
                    return None
                passed = float(val) <= threshold  # smaller resolvable spacing is better
                res.measurements.append(Measurement(
                    label=label, value=float(val), unit="mm",
                    spec=f"≤ {threshold:.1f} mm", passed=passed,
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
