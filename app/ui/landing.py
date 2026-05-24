"""Landing page shown when no DICOM series is loaded.

Three "how it works" columns, the phantom-only / not-a-medical-device
warning + info, and the in-session history list (if any). The entry
point calls ``st.stop()`` after this; nothing below it should run when
the user hasn't picked a series yet.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from . import badges


def render() -> None:
    st.markdown("## How it works")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("### 1. Upload")
        st.markdown(
            "Drop a zipped ACR phantom series (or individual `.dcm` files) "
            "into the sidebar. Both T1/T2 axial series and sagittal scouts work."
        )
    with c2:
        st.markdown("### 2. Pick a series")
        st.markdown(
            "The app picks the analysis from the series you choose:"
            " **11-slice axial** runs the full ACR protocol; a"
            " **single sagittal image** runs the S-I length check."
        )
    with c3:
        st.markdown("### 3. Run + Report")
        st.markdown(
            "Axial runs five automated tests (Analysis tab) and, on a "
            "separate **Manual scoring** tab, two visual tests. Sagittal runs "
            "one automated test. Export a PDF + CSV when done."
        )

    st.divider()
    st.markdown("### Important — read before uploading")
    st.warning(
        "**Phantom data only.** This MVP is intended for ACR phantom QA. "
        "Do NOT upload patient (PHI) DICOMs to a publicly-hosted instance. "
        "Even though uploads are not persisted, de-identify your data first."
    )
    st.info(
        "**Not a medical device.** Numerical results are decision-support for "
        "physicists. Final QA approval and clinical use of any scanner "
        "remain the responsibility of the supervising physicist."
    )

    if st.session_state.history:
        st.divider()
        st.markdown("### Sessions completed this browser tab")
        for s in reversed(st.session_state.history):
            st.markdown(
                f"- **{escape(s['datetime'])}** · {escape(s['scanner'])} · "
                f"{escape(s['sequence'])} · {badges.status_badge(s['verdict'])} "
                f"(pass {s['counts']['PASS']} · fail {s['counts']['FAIL']} · "
                f"review {s['counts']['REVIEW']})",
                unsafe_allow_html=True,
            )
