"""In-browser-session history of completed QA runs.

History is intentionally in-memory only — ``_snapshot_run`` stashes the full
``DicomSeries`` (with its ``pydicom.FileDataset`` objects) and the dict of
``TestResult`` (which holds PIL images from matplotlib). Streamlit doesn't
persist session state to disk, so this is fine; if a future "save session"
feature lands, these objects will need a serializer first.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests.base import TestResult, verdict_of


def snapshot_run(series: DicomSeries, results: dict[str, TestResult]) -> dict:
    """Build a serializable-ish snapshot of a completed run."""
    md = series.metadata
    verdict, counts = verdict_of(results.values())
    return {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "datetime": datetime.now().isoformat(timespec="seconds"),
        "scanner": f"{md.manufacturer} {md.model}".strip(),
        "field_strength": md.field_strength_t,
        "patient_id": md.patient_id,
        "series_description": md.series_description,
        "sequence": md.sequence,
        "n_slices": md.n_slices,
        "verdict": verdict,
        "counts": counts,
        "results": results,    # in-memory only
        "series": series,
    }


def render() -> None:
    st.subheader("Past QA runs (this browser session)")
    st.caption(
        "History is in-memory and lives only as long as this browser tab. "
        "Use the Export tab to save permanent PDFs."
    )
    if not st.session_state.history:
        st.info("Save a run from the Results tab to populate history.")
        return

    for i, s in enumerate(reversed(st.session_state.history)):
        with st.expander(
            f"{s['datetime']} · {s['scanner'] or '—'} · "
            f"{s['sequence']} · {s['verdict']}",
            expanded=False,
        ):
            a, b, c, d, e = st.columns(5)
            a.metric("Verdict", s["verdict"])
            b.metric("Pass", s["counts"]["PASS"])
            c.metric("Fail", s["counts"]["FAIL"])
            d.metric("Review", s["counts"]["REVIEW"])
            e.metric("Error", s["counts"]["ERROR"])
            st.markdown(
                f"<span class='mri-small'>"
                f"Patient/Phantom ID: {s['patient_id'] or '—'} · "
                f"Series: {s['series_description'] or '—'} · "
                f"Slices: {s['n_slices']}"
                f"</span>",
                unsafe_allow_html=True,
            )
            if st.button("Re-open this run", key=f"reopen_{i}"):
                st.session_state.series = s["series"]
                st.session_state.results = dict(s["results"])
                st.rerun()
