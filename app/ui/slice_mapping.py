"""Axial Analysis tab — algorithm inputs, ACR slice role mapping, and the
"Run all automated tests" trigger.

The user lands here after picking a multi-slice series. Everything above
the Run button is an input to the algorithms; the button kicks off
``results_view.run_automated_tests`` and surfaces the automated-only
subset inline so the user sees what the run produced without empty
REVIEW rows for un-scored visual tests.
"""

from __future__ import annotations

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries, default_acr_slice_map
from ..qa_tests import AnalysisMode, TestSpec
from . import analysis_inputs, results_view
from .badges import normalize_img


def render(
    series: DicomSeries,
    test_order: list[TestSpec],
    analysis_mode: AnalysisMode,
) -> None:
    md = series.metadata
    st.subheader("Analysis inputs")
    st.caption(
        "Everything above the **Run all automated tests** button is an "
        "input to the algorithms. The dropdowns are pre-selected from the "
        "loaded series — change them only if the defaults are wrong."
    )
    analysis_inputs.render(series, key_prefix="axial_inputs")

    st.divider()
    st.subheader("ACR slice role mapping")
    st.write(
        "ACR procedures reference **slice 1** (bars/wedges), **5** (central), "
        "**7** (uniform region), and **11** (superior wedges). Auto-mapping uses "
        "InstanceNumber. Override below if your series is non-standard."
    )
    default = default_acr_slice_map(md.n_slices)
    cols = st.columns(4)
    new_map: dict[int, int] = {}
    for col, role in zip(cols, [1, 5, 7, 11]):
        with col:
            cur = series.acr_slice_map.get(role, default.get(role, 0))
            v = st.number_input(
                f"ACR slice {role} → physical index",
                min_value=1, max_value=max(1, md.n_slices),
                value=min(int(cur) + 1, md.n_slices), step=1,
            )
            new_map[role] = int(v) - 1
            preview = normalize_img(series.pixel_array[int(v) - 1])
            st.image(preview, caption=f"Physical slice {int(v)}", width=180)

    if len(set(new_map.values())) < 4:
        st.warning(
            "Two or more ACR roles are mapped to the same physical slice. "
            "This is unusual — confirm before running QA."
        )

    series.acr_slice_map = {**series.acr_slice_map, **new_map}
    st.session_state.series = series

    st.divider()
    st.markdown("### Run automated tests")
    st.caption(
        "Runs the five automated ACR tests against the slice mapping above. "
        "The two visual tests (HCR, LCD) are scored separately on the "
        "**Manual scoring** tab — typically only worth doing once the "
        "automated tests pass."
    )
    if st.button("Run all automated tests", type="primary"):
        results = dict(st.session_state.results)
        results.update(results_view.run_automated_tests(series, test_order))
        st.session_state.results = results
        st.rerun()

    # Show the results inline after a run, mirroring how the sagittal mode
    # surfaces them on the same tab that hosts the Run button.
    if st.session_state.results:
        st.divider()
        results_view.render(
            test_order, analysis_mode, series,
            key_prefix="slice_run_tab",
            scope="automated",
        )
