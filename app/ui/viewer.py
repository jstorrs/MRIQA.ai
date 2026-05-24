"""Slice-viewer tab — scrolls through the loaded series with a shared
window level/width that persists across slices (DICOM-viewer style)."""

from __future__ import annotations

import numpy as np
import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from .badges import normalize_img


def render(series: DicomSeries) -> None:
    st.subheader("Slice viewer")
    n = series.metadata.n_slices
    vol = series.pixel_array

    # Volume-wide auto window so the same level/width applies to ALL slices
    # instead of resetting per slice.
    auto_wl = round(float(np.nanmean(vol)), 1) if vol.size else 0.0
    auto_ww = round(float(max(1.0, np.nanstd(vol) * 4 + 1)), 1) if vol.size else 1.0
    if "view_wl" not in st.session_state:
        st.session_state.view_wl = auto_wl
    if "view_ww" not in st.session_state:
        st.session_state.view_ww = auto_ww

    def _reset_window():
        st.session_state.view_wl = auto_wl
        st.session_state.view_ww = auto_ww

    if n <= 1:
        idx = 1
        st.info("Series has only one slice; slider disabled.")
    else:
        idx = st.slider("Slice index (1-based)", 1, n, 1)

    cwl, cww, cbtn = st.columns([2, 2, 1])
    cwl.number_input("Window level", key="view_wl", step=10.0)
    cww.number_input("Window width", key="view_ww", min_value=1.0, step=10.0)
    with cbtn:
        st.markdown("<div style='height:1.7em'></div>", unsafe_allow_html=True)
        st.button(
            "Auto", on_click=_reset_window, width="stretch",
            help="Reset window to the auto level/width for this series.",
        )
    st.caption("Window level/width applies to all slices as you scroll.")

    img = normalize_img(vol[idx - 1], wl=st.session_state.view_wl, ww=st.session_state.view_ww)
    st.image(img, caption=f"Slice {idx} of {n}", width=560)
