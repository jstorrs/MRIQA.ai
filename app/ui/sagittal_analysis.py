"""Sagittal Analysis tab — algorithm inputs, image picker, and S-I length run.

A single-image series is treated as the sagittal-localizer S-I length
analysis. The image picker mirrors the axial slice-mapping picker for
consistency; with a 1-image upload it is trivially 1 of 1.
"""

from __future__ import annotations

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests import TestSpec, run_test
from . import analysis_inputs
from .badges import normalize_img


def render(series: DicomSeries, test_order: list[TestSpec]) -> None:
    md = series.metadata
    st.subheader("Analysis inputs")
    st.caption(
        "Everything above the **Run S-I length test** button is an input "
        "to the algorithm. The dropdowns are pre-selected from the loaded "
        "series — change them only if the defaults are wrong."
    )
    analysis_inputs.render(series, key_prefix="sagittal_inputs", show_sequence=False)

    st.divider()
    st.subheader("Sagittal image")
    st.caption(
        "The S-I length is measured on a single sagittal scout. The "
        "selector mirrors the axial slice-mapping picker for consistency; "
        "with a 1-image upload it is trivially 1 of 1."
    )
    cols = st.columns(4)
    with cols[0]:
        sag_idx = st.number_input(
            "Sagittal image → physical index",
            min_value=1, max_value=max(1, md.n_slices),
            value=1, step=1, key="sagittal_image_index",
        )
        preview = normalize_img(series.pixel_array[int(sag_idx) - 1])
        st.image(preview, caption=f"Physical slice {int(sag_idx)}", width=180)

    st.divider()
    st.subheader("Run")
    st.caption(
        f"Measures the phantom's superior-inferior length on the sagittal "
        f"scout against the spec nominal "
        f"({series.spec.si_length_mm:.0f} mm ± {series.spec.length_tolerance_mm:.0f} mm)."
    )
    if st.button("Run S-I length test", type="primary"):
        results = dict(st.session_state.results)
        for t in test_order:
            results[t.id] = run_test(t, series)
        st.session_state.results = results
        st.rerun()
