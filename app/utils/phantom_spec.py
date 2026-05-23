"""Phantom specifications.

Every numerical constant tied to a *specific* ACR phantom model lives in a
``PhantomSpec`` here, never in a test module. A QA test reads what it needs
from ``series.spec`` (the spec attached to the loaded series) so the same
algorithm runs unchanged across phantom models.

Sources
-------
Both ``LARGE`` and ``MEDIUM`` values come from the **ACR Large and Medium
Phantom Test Guidance, 10.19.2022** (file
``MR_ACR_Large_Med_Phantom_Guidance_102022`` at the project root).
Specific section references are noted on each field.

Where the 2022 guidance lists separate ACR-T1 and ACR-T2 LCD thresholds
for the same field-strength band, the engine uses the stricter of the
two (T1) since the current run() loop applies a single threshold per
series.

LARGE values were updated from earlier 2015-era MVP defaults to align
with the 2022 guidance — most notably:
  * Geometric-accuracy tolerance ±2.0 → ±3.0 mm (§ 1.4 / Table 3).
  * PIU thresholds swapped between field-strength bands so the lower
    threshold applies at 3 T (§ 5.4 / Table 4).
  * LCD thresholds raised to *total* spokes across all four LCD slices
    (≥ 37 at 3 T, ≥ 30 at 1.5 T) (§ Table 5).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhantomSpec:
    # --- identity ---
    name: str                              # human label, e.g. "ACR Large MRI Phantom"
    short_name: str                        # filename/log slug, e.g. "large"

    # --- geometry ---
    diameter_mm: float                     # axial in-plane diameter (slices 1 & 5)
    si_length_mm: float                    # superior-inferior length (sagittal localizer)
    length_tolerance_mm: float             # ± tolerance for both diameter and S-I length

    # --- segmentation plausibility heuristics ---
    radius_plausible_mm: tuple[float, float]      # (lo, hi) for phantom_quality_warnings
    diameter_plausible_mm: tuple[float, float]    # (lo, hi) for geo-accuracy detector sanity
    si_length_plausible_mm: tuple[float, float]   # (lo, hi) for geo-accuracy detector sanity

    # --- protocol ---
    n_protocol_slices: int                 # standard axial slice count (11 for both ACR phantoms)
    slice_role_indices: dict[int, int]     # ACR slice role -> physical index for the standard protocol

    # --- slice 1: slice thickness ---
    nominal_slice_thickness_mm: float      # 5.0 mm for both ACR phantoms
    slice_thickness_tolerance_mm: float    # ± tolerance

    # --- slice 1 & 11: slice position ---
    bar_diff_tolerance_mm: float           # |left-right bar length| ≤ this

    # --- slice 1: high-contrast resolution insert ---
    resolution_array_sizes_mm: tuple[float, ...]   # ordered largest→smallest
    resolution_pass_threshold_mm: float            # smallest array that must be resolvable

    # --- slice 7: image intensity uniformity (PIU) ---
    piu_large_roi_area_cm2: float          # large ROI area
    piu_small_roi_area_cm2: float          # sliding small ROI area
    piu_threshold_lowfield_percent: float  # action limit < 3 T
    piu_threshold_3t_percent: float        # action limit ≥ 3 T

    # --- slice 7: percent signal ghosting (PSG) ---
    ghosting_large_roi_area_cm2: float
    ghosting_air_roi_long_mm: float
    ghosting_air_roi_short_mm: float
    ghosting_air_offset_mm: float          # distance outside phantom edge for the four air ROIs
    ghosting_threshold_percent: float

    # --- slices 8–11: low-contrast object detectability (LCD) ---
    lcd_slices: tuple[int, ...]            # ACR slice roles containing spoke patterns
    lcd_threshold_3t: int                  # total spokes required at ≥ 3 T
    lcd_threshold_lowfield: int            # total spokes required at < 3 T


LARGE = PhantomSpec(
    name="ACR Large MRI Phantom",
    short_name="large",
    # § Table 1 / Table 3 — Large internal dimensions
    diameter_mm=190.0,
    si_length_mm=148.0,
    # § 1.4 — Large pass/fail limit is ±3.0 mm (Medium is ±2.0)
    length_tolerance_mm=3.0,
    # Plausibility bounds for the segmented phantom (nominal radius 95 mm).
    radius_plausible_mm=(70.0, 115.0),
    diameter_plausible_mm=(160.0, 220.0),
    si_length_plausible_mm=(130.0, 165.0),
    # § 0.3 + Table 2 — 11-slice axial protocol
    n_protocol_slices=11,
    slice_role_indices={1: 0, 5: 4, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10},
    # § 3.4 — slice thickness limits are identical between Large and Medium
    nominal_slice_thickness_mm=5.0,
    slice_thickness_tolerance_mm=0.7,
    # § 4.4 — slice position limits are identical between Large and Medium
    bar_diff_tolerance_mm=5.0,
    # § Table 1 + § 2.2 — older Large phantoms have three resolution arrays;
    # newer Large phantoms have four arrays (1.1, 1.0, 0.9, 0.8). We default to
    # the legacy three-array set so existing phantoms render correctly; sites
    # with the newer four-array Large phantom can extend this tuple.
    resolution_array_sizes_mm=(1.1, 1.0, 0.9),
    # § 2.4 — required minimum resolution is 1.0 mm for both phantoms
    resolution_pass_threshold_mm=1.0,
    # § Table 4 — Large PIU ROI areas and thresholds
    piu_large_roi_area_cm2=200.0,           # 195–205 cm² band, nominal 200
    piu_small_roi_area_cm2=1.0,
    piu_threshold_lowfield_percent=87.5,    # < 3 T
    piu_threshold_3t_percent=82.0,          # 3 T (lower because of dielectric effects)
    # § Table 4 + § 6.2 — Large ghosting reuses the same large ROI as PIU
    ghosting_large_roi_area_cm2=200.0,
    # § 6.2 — 10 cm² air ROIs with ~4:1 aspect ratio
    ghosting_air_roi_long_mm=40.0,
    ghosting_air_roi_short_mm=10.0,
    ghosting_air_offset_mm=12.0,
    # § 6.4 — PSG limit is 3.0 % for both phantoms
    ghosting_threshold_percent=3.0,
    # § Table 5 — Large LCD limits (total spokes across slices 8–11)
    lcd_slices=(8, 9, 10, 11),
    lcd_threshold_3t=37,         # ≥ 37 total spokes at 3 T (T1 & T2 the same)
    lcd_threshold_lowfield=30,   # ≥ 30 total spokes at 1.5 T (ACR-T1; T2 is ≥ 25)
)


MEDIUM = PhantomSpec(
    name="ACR Medium MRI Phantom",
    short_name="medium",
    # § Table 1 / Table 3 — Medium internal dimensions
    diameter_mm=165.0,
    si_length_mm=134.0,
    # § 1.4 — Medium pass/fail limit is ±2.0 mm
    length_tolerance_mm=2.0,
    # Plausibility bounds for the segmented phantom (nominal radius 82.5 mm; the
    # slice-thickness slice has a slightly smaller imaged outline). Tightened so
    # accidentally selecting MEDIUM with a Large-phantom acquisition surfaces a
    # warning.
    radius_plausible_mm=(60.0, 95.0),
    diameter_plausible_mm=(135.0, 195.0),
    si_length_plausible_mm=(115.0, 150.0),
    # § 0.3 + Table 2 — both ACR phantoms use the same 11-slice axial protocol
    n_protocol_slices=11,
    slice_role_indices={1: 0, 5: 4, 7: 6, 8: 7, 9: 8, 10: 9, 11: 10},
    # § 3.4 — slice thickness limits are identical between Large and Medium
    nominal_slice_thickness_mm=5.0,
    slice_thickness_tolerance_mm=0.7,
    # § 4.4 — slice position limits are identical between Large and Medium
    bar_diff_tolerance_mm=5.0,
    # § Table 1 + § 2.2 — Medium phantom has four resolution arrays
    resolution_array_sizes_mm=(1.1, 1.0, 0.9, 0.8),
    # § 2.4 — required minimum resolution is 1.0 mm for both phantoms
    resolution_pass_threshold_mm=1.0,
    # § Table 4 — Medium PIU ROI areas and thresholds
    piu_large_roi_area_cm2=160.0,           # 155–165 cm² band, nominal 160
    piu_small_roi_area_cm2=1.0,
    piu_threshold_lowfield_percent=90.0,    # < 3 T
    piu_threshold_3t_percent=85.0,          # 3 T
    # § Table 4 + § 6.2 — Medium ghosting reuses the same large ROI as PIU
    ghosting_large_roi_area_cm2=160.0,
    # § 6.2 — 10 cm² air ROIs with ~4:1 aspect ratio; same as Large
    ghosting_air_roi_long_mm=40.0,
    ghosting_air_roi_short_mm=10.0,
    ghosting_air_offset_mm=12.0,
    # § 6.4 — Medium PSG limit is 3.0 %, identical to Large
    ghosting_threshold_percent=3.0,
    # § Table 5 — Medium LCD limits
    lcd_slices=(8, 9, 10, 11),
    lcd_threshold_3t=37,         # ≥ 37 total spokes at 3 T (T1 & T2 the same)
    lcd_threshold_lowfield=30,   # ≥ 30 total spokes at 1.5 T (ACR-T1; T2 is ≥ 25)
)


PHANTOMS: dict[str, PhantomSpec] = {
    LARGE.short_name: LARGE,
    MEDIUM.short_name: MEDIUM,
}


def default_phantom() -> PhantomSpec:
    """Spec assumed when nothing is selected. Today that's the Large phantom."""
    return LARGE
