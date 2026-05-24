"""Manual scoring tab — the two ACR tests defined as visual rather than
algorithmic (High-Contrast Resolution and Low-Contrast Detectability).

The app shows the correctly-located images; the user records what they
see, then saves. Saved scores live in ``st.session_state.results`` under
the test_id and get rolled into the overall verdict on Results.
"""

from __future__ import annotations

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests import (
    AnalysisMode,
    TestSpec,
    high_contrast_resolution,
    low_contrast_detectability,
)
from . import results_view


def _cached_visual_images(
    cache_key: str, series: DicomSeries, runner, existing,
):
    """Return the annotated images for a visual test without re-running
    its detector every Streamlit rerun. Saved test results win over the
    cache; a per-``id(series)`` key invalidates when the user switches
    series."""
    if existing is not None and existing.annotated_images:
        return existing.annotated_images
    series_key = id(series)
    cached = st.session_state.get(cache_key)
    if cached is None or cached[0] != series_key:
        images = runner(series, spec=series.spec).annotated_images
        st.session_state[cache_key] = (series_key, images)
        return images
    return cached[1]


def _render_hcr(series: DicomSeries) -> None:
    st.markdown("### High-contrast resolution")
    st.caption(
        "On slice 1, look at the UL and LR hole arrays in the zoomed crops below."
    )
    images = _cached_visual_images(
        "_visual_hcr_cache", series,
        high_contrast_resolution.run,
        st.session_state.results.get("high_contrast_resolution"),
    )
    for cap, im in images:
        st.image(im, caption=cap, width="stretch")

    # Drop sizes the detector didn't actually see (older Large phantoms
    # have three grids; the spec also lists 0.8 mm for the four-grid
    # variant, which would be a nonsense choice on a three-grid scan).
    res_sizes = high_contrast_resolution.detect_present_sizes(
        series, spec=series.spec,
    )
    if not res_sizes:
        res_sizes = list(series.spec.resolution_array_sizes_mm)
    res_default_idx = (
        res_sizes.index(series.spec.resolution_pass_threshold_mm)
        if series.spec.resolution_pass_threshold_mm in res_sizes
        else len(res_sizes) // 2
    )
    cspec, cul, clr = st.columns(3)
    threshold = cspec.selectbox(
        "Required smallest row (mm)", res_sizes, index=res_default_idx,
    )
    ul = cul.selectbox(
        "UL smallest resolvable", [None, *res_sizes],
        format_func=lambda x: "—" if x is None else f"{x} mm",
    )
    lr = clr.selectbox(
        "LR smallest resolvable", [None, *res_sizes],
        format_func=lambda x: "—" if x is None else f"{x} mm",
    )
    if st.button("Save resolution scoring"):
        res = high_contrast_resolution.run(
            series, spec=series.spec,
            user_input={"UL": ul, "LR": lr, "spec": threshold},
        )
        st.session_state.results["high_contrast_resolution"] = res
        st.success("Saved.")


def _render_lcd(series: DicomSeries) -> None:
    lcd_slices = series.spec.lcd_slices
    lcd_range_label = f"{lcd_slices[0]}–{lcd_slices[-1]}"
    st.markdown("### Low-contrast object detectability")
    st.caption(f"Count complete spokes visible on each of slices {lcd_range_label}.")

    images = _cached_visual_images(
        "_visual_lcd_cache", series,
        low_contrast_detectability.run,
        st.session_state.results.get("low_contrast_detectability"),
    )
    if images:
        img_cols = st.columns(min(len(images), 4))
        for i, (cap, im) in enumerate(images):
            with img_cols[i % len(img_cols)]:
                st.image(im, caption=cap, width="stretch")

    with st.form("lcd_scoring_form", clear_on_submit=False):
        cs = st.columns(len(lcd_slices))
        spoke_counts: dict[int, int] = {}
        for col, s in zip(cs, lcd_slices):
            with col:
                spoke_counts[s] = st.number_input(
                    f"Slice {s} spokes",
                    min_value=0, max_value=10, value=0, step=1,
                    key=f"lcd_spokes_{s}",
                )
        submitted = st.form_submit_button("Save LCD scoring")
    if submitted:
        res = low_contrast_detectability.run(
            series, spec=series.spec, user_input=spoke_counts,
        )
        st.session_state.results["low_contrast_detectability"] = res
        st.success("Saved.")


def render(
    series: DicomSeries,
    test_order: list[TestSpec],
    analysis_mode: AnalysisMode,
) -> None:
    st.subheader("Visual / manual scoring")
    st.info(
        "**Two ACR tests are visual** — High-Contrast Spatial Resolution and "
        "Low-Contrast Object Detectability. The ACR manual defines these as "
        "human-judged tests, so the app shows you the correctly-located "
        "images and you record what you see. They stay at status REVIEW "
        "until you score and save."
    )

    automated_results = {
        tid: r for tid, r in st.session_state.results.items()
        if tid not in results_view.VISUAL_TEST_IDS
    }
    if automated_results and any(
        r.status_text() == "FAIL" for r in automated_results.values()
    ):
        st.warning(
            "One or more automated tests **failed**. Manual scoring is "
            "usually a waste of time on a series with a clear acquisition "
            "or calibration problem — fix the upstream issue first unless "
            "you need a complete report."
        )

    _render_hcr(series)
    st.divider()
    _render_lcd(series)

    # Show just the manual results inline once at least one visual test
    # has been scored. The full automated+manual roll-up lives on Results.
    manual_done = any(
        tid in results_view.VISUAL_TEST_IDS for tid in st.session_state.results
    )
    if manual_done:
        st.divider()
        results_view.render(
            test_order, analysis_mode, series,
            key_prefix="manual_tab", scope="manual",
        )
