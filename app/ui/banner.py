"""Status banner helper.

One place builds the ``.mri-banner`` div used by the entry-point banner
strip and the verdict banner on the Results view. The CSS classes
``mri-banner-<status>`` are declared in the page-config stylesheet in
``streamlit_app.py``; ``status`` must be one of:

  ``PASS`` · ``FAIL`` · ``REVIEW`` · ``ERROR`` · ``dash``
"""

from __future__ import annotations

from typing import Literal

import streamlit as st

BannerStatus = Literal["PASS", "FAIL", "REVIEW", "ERROR", "dash"]


def banner(html: str, *, status: BannerStatus = "dash") -> None:
    """Render an ``.mri-banner`` div containing ``html``."""
    st.markdown(
        f"<div class='mri-banner mri-banner-{status}'>{html}</div>",
        unsafe_allow_html=True,
    )
