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
from ..utils.geometry import contiguous_runs
from ..utils.phantom import localize_phantom
from ..utils.phantom_spec import PhantomSpec
from ..utils.viz import render_annotated
from .base import Measurement, TestResult


def crop_resolution_insert(
    image: np.ndarray, geom, corner: str,
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Return ``(crop, bbox)`` for a zoomed view of the UL or LR resolution
    insert. ``bbox`` is ``(y0, y1, x0, x1)`` in image coordinates.

    The inserts sit just inside the upper-left and lower-right of the
    phantom, roughly at radius 0.65*r along the diagonals.
    """
    H, W = image.shape
    bb = _detect_resolution_bbox(image, geom)
    if bb is None:
        # Geometric fallback relative to the phantom centre.
        cy, cx, r = geom.cy_px, geom.cx_px, geom.radius_px
        bb = (int(cy + 0.34 * r), int(cy + 0.58 * r),
              int(cx - 0.28 * r), int(cx + 0.70 * r))

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


def _cluster_runs(active, min_gap_for_split):
    """Group contiguous-True runs in `active`. Runs separated by fewer than
    `min_gap_for_split` False columns are merged (treated as within-grid
    jitter rather than real inter-grid spacing).

    Returns a list of (start, end_inclusive) tuples.
    """
    runs = contiguous_runs(active)
    if not runs:
        return []
    merged = [runs[0]]
    for s, e in runs[1:]:
        ps, pe = merged[-1]
        if s - pe - 1 < min_gap_for_split:
            merged[-1] = (ps, e)
        else:
            merged.append((s, e))
    return merged


def _detect_resolution_grids(image, geom):
    """Locate the hole-array block in the lower-centre of slice 1, and
    enumerate the individual grid clusters within it.

    The arrays are faint mid-level signal (brighter than the dark insert
    interior, much darker than the bright phantom walls). We search a
    generous window below the phantom centre, threshold for that mid band,
    take the densest contiguous row run, then cluster the column profile
    into per-grid runs.

    Returns (bbox, clusters_abs) or (None, None), where
        bbox        = (ay0, ay1, ax0, ax1) spanning all grids
        clusters_abs = list of (col_start, col_end_inclusive) in image coords,
                       one per detected grid (left → right)
    """
    cy, cx, r = geom.cy_px, geom.cx_px, geom.radius_px
    H, W = image.shape
    r0 = max(0, int(cy + 0.20 * r)); r1 = min(H, int(cy + 0.72 * r))
    # Right edge generously beyond the 3-array span so 4-array phantoms'
    # rightmost 0.8 mm grid sits inside the search window.
    c0 = max(0, int(cx - 0.28 * r)); c1 = min(W, int(cx + 0.70 * r))
    if r1 - r0 < 6 or c1 - c0 < 20:
        return None, None
    win = image[r0:r1, c0:c1]
    void = np.percentile(win, 15)
    phantom = np.percentile(win, 97)
    span = phantom - void
    if span < 1e-6:
        return None, None
    lo = void + 0.04 * span
    hi = void + 0.35 * span
    arr = (win > lo) & (win < hi)
    rc = arr.sum(axis=1)
    runs = contiguous_runs(rc > max(3, rc.max() * 0.20))
    L, rs, re = max(((e - s + 1, s, e) for s, e in runs), default=(0, 0, 0))
    if L < 6:
        return None, None
    cc = arr[rs:re + 1].sum(axis=0)
    # Lower per-column threshold so the highest-resolution grid (weakest
    # mid-band signal because the holes are tiny) doesn't fall under the bar.
    active = cc > max(2, cc.max() * 0.08)
    # The inter-grid gap (solid block between resolution pairs) is typically
    # several pixels wide; jitter within a grid is at most one or two.
    clusters = _cluster_runs(active, min_gap_for_split=3)
    # Drop tiny clusters (single-pixel speckle) — a real grid is at least 3 px.
    clusters = [(s, e) for s, e in clusters if e - s + 1 >= 3]
    if not clusters:
        return None, None
    ay0, ay1 = r0 + rs, r0 + re
    ax0, ax1 = c0 + clusters[0][0], c0 + clusters[-1][1]
    # Plausibility for the ACR resolution block; width bound covers both the
    # 3-array (~85 px @ 1 mm) and 4-array (~120 px) inserts.
    if not (8 <= (ay1 - ay0) <= 45 and 35 <= (ax1 - ax0) <= 130):
        return None, None
    clusters_abs = [(c0 + s, c0 + e) for s, e in clusters]
    return (ay0, ay1, ax0, ax1), clusters_abs


def _detect_resolution_bbox(image, geom):
    """Backward-compatible bbox-only view of :func:`_detect_resolution_grids`."""
    bbox, _ = _detect_resolution_grids(image, geom)
    return bbox


def _grid_count_from_bbox(bbox, clusters) -> int | None:
    """Decide how many resolution-array grids are present from the detected
    bbox + cluster set.

    Measures the aspect ratio of the **rendered crop** (bbox + padding
    matching :func:`crop_resolution_insert` 'full' mode) rather than the raw
    bbox. Two reasons: (1) the raw bbox height covers the dominant-signal
    row only, which makes its aspect ratio uninformative; and (2) the
    rendered crop is what the user can visually compare, so its aspect is
    what they'd naturally trust. Empirically:
        * 3-array rendered crop: aspect ≈ 2.7
        * 4-array rendered crop: aspect ≈ 3.3
    Threshold at 3.0.

    The cluster count is used as a confirmation: when it lands at 3 or 4 we
    trust it over the aspect ratio (clean detection); otherwise the ratio
    wins.
    """
    if bbox is None:
        return None
    ay0, ay1, ax0, ax1 = bbox
    bbox_w_px = max(1, ax1 - ax0)
    bbox_h_px = max(1, ay1 - ay0)
    # Match crop_resolution_insert's 'full' padding so the aspect we evaluate
    # equals the aspect of the figure shown to the user.
    crop_w_px = bbox_w_px + 9   # x: c0-4 to c1+5
    crop_h_px = bbox_h_px + 11  # y: r0-5 to r1+6
    aspect_n = 4 if crop_w_px / crop_h_px >= 3.0 else 3
    cluster_n = len(clusters) if clusters else 0
    if cluster_n in (3, 4):
        return cluster_n
    return aspect_n


def detect_present_sizes(series: DicomSeries, spec: PhantomSpec | None = None) -> list[float]:
    """Return the resolution-array sizes physically present on this phantom,
    in the same left→right (largest→smallest) order as
    ``spec.resolution_array_sizes_mm``.

    Older Large phantoms have only the three 1.1 / 1.0 / 0.9 mm arrays;
    current Large + every Medium phantom adds the fourth 0.8 mm array. We
    classify via the bbox aspect ratio of the detected insert, with the
    cluster count used as a confirmation when it lands at a plausible value
    (see :func:`_grid_count_from_bbox`). Falls back to the full spec list on
    detection failure.
    """
    if spec is None:
        spec = series.spec
    sizes = list(spec.resolution_array_sizes_mm)
    try:
        img = series.slice(1).astype(np.float32)
        geom = localize_phantom(img)
        bbox, clusters = _detect_resolution_grids(img, geom)
    except (KeyError, ValueError, IndexError):
        # KeyError: ACR slice 1 not mapped. ValueError: localize_phantom on a
        # bad image. IndexError: degenerate detector geometry.
        return sizes
    n = _grid_count_from_bbox(bbox, clusters)
    if n is not None and n < len(sizes):
        return sizes[:n]
    return sizes


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
    spec = spec or series.spec
    res = TestResult(
        test_id="high_contrast_resolution",
        test_name="High-Contrast Spatial Resolution",
        automated=False,
        passed=None,
    )
    with res.capture_failures():
        img = series.slice(1).astype(np.float32)
        geom = localize_phantom(img)

        full_crop, _ = crop_resolution_insert(img, geom, "full")
        bbox, clusters = _detect_resolution_grids(img, geom)
        spec_sizes = list(spec.resolution_array_sizes_mm)
        spec_n = len(spec_sizes)
        detected_n = _grid_count_from_bbox(bbox, clusters)
        # Build the label from the sizes physically present on this phantom.
        # _grid_count_from_bbox primarily uses the bbox aspect ratio (which
        # remains correct even when the cluster detector merges the grids
        # into a single run).
        if detected_n is not None and detected_n < spec_n:
            present_sizes = spec_sizes[:detected_n]
        else:
            present_sizes = spec_sizes
        sizes_label = " | ".join(f"{s:.1f}" for s in present_sizes)
        sizes_csv = " / ".join(f"{s:.1f}" for s in present_sizes)
        count_note = ""
        if detected_n is not None:
            cluster_n = len(clusters) if clusters else 0
            count_note = (
                f" Detector inferred {detected_n} grid"
                f"{'s' if detected_n != 1 else ''} from the insert aspect ratio"
            )
            if cluster_n and cluster_n != detected_n:
                count_note += f" (cluster count was {cluster_n})"
            if detected_n > spec_n:
                count_note += f"; spec expects {spec_n}"
                res.add_warning(
                    f"Detected {detected_n} resolution grid(s) but the {spec.short_name} "
                    f"spec expects {spec_n}. Verify the crop and the selected phantom variant.",
                    severity="medium",
                )
            count_note += "."

        def _draw_full(ax):
            ax.set_title(
                f"Slice 1 — resolution insert: {sizes_label} mm (left→right)",
                fontsize=9,
            )
        res.annotated_images.append((
            f"Slice 1 — resolution insert ({sizes_csv} mm, left→right). "
            "UL blocks = vertical holes (upper), LR blocks = horizontal holes (lower)."
            + count_note,
            render_annotated(full_crop, "", _draw_full, figsize=(8.0, 3.0))))

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
    return res
