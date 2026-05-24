"""MRIQA.ai — Streamlit entry point.

Run locally:
    streamlit run streamlit_app.py

Deployed: Streamlit Community Cloud points at this file.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

# ``streamlit run`` adds the script's directory to sys.path before any
# `from app...` import resolves, so no manual sys.path manipulation is
# needed here. See streamlit.web.bootstrap (the line `sys.path.insert(0,
# os.path.dirname(main_script_path))`).
from app.io_dicom.dicom_loader import (
    DicomSeries, load_series, load_series_from_folder, validate_series,
)
from app.qa_tests import (
    AXIAL_TEST_ORDER, SAGITTAL_TEST_ORDER, AnalysisMode, infer_analysis_mode,
)
from app.ui import (
    auth, export, history, landing, manual_scoring,
    results_view, sagittal_analysis, slice_mapping,
    uploads, validation, viewer,
)
from app.ui.banner import banner
from app.ui.uploads import SeriesCatalogEntry

EXPORTS_DIR = Path(__file__).resolve().parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)
APP_VERSION = "0.2.0-mvp"


# --------------------------------------------------------------------------- #
# Page setup                                                                  #
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="MRIQA.ai — ACR Phantom QA",
    page_icon="\U0001F9E0",   # brain emoji as favicon
    layout="wide",
)

# Tiny CSS polish — quieter title, tighter spacing
st.markdown(
    """
    <style>
      h1 { font-weight: 600; }
      .block-container { padding-top: 1.5rem; }
      .stTabs [role=tablist] button { font-weight: 500; }
      .mri-banner {
          padding: 0.9rem 1.1rem; border-radius: 8px;
          border: 1px solid #e3e6eb; margin-bottom: 0.4rem;
      }
      .mri-banner-PASS  { background:#ecf7ee; border-color:#bfe1c6; }
      .mri-banner-FAIL  { background:#fdecea; border-color:#f4b9b3; }
      .mri-banner-REVIEW{ background:#fff5e1; border-color:#f1d6a3; }
      .mri-banner-ERROR { background:#f1f1f1; border-color:#cccccc; }
      .mri-banner-dash  { background:#f7f9fc; border-color:#e3e6eb; }
      .mri-small { color:#5a6473; font-size:0.85em; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("MRIQA.ai — ACR Phantom QA")

# ---- Password gate (shared password via Streamlit secrets) ---------------- #
if not auth.check_password():
    st.stop()

st.caption(
    "Decision-support tool for medical physicists. "
    "**Not a medical device. Not for diagnostic use.** "
    "Thresholds from the ACR Large and Medium Phantom Test Guidance (Oct 2022)."
)

# --------------------------------------------------------------------------- #
# Session state init                                                          #
# --------------------------------------------------------------------------- #

# series_catalog: list[SeriesCatalogEntry] (see app/ui/uploads.py),
# accumulated across upload batches and indexed by selected_series_uid.
# uploader_nonce: bumping re-mounts the file_uploader widget as a fresh,
# empty drop zone so the persistent "1 file uploaded" list goes away.
_SESSION_DEFAULTS = {
    "series": None,
    "results": {},
    "history": [],
    "validation_log": [],
    "series_warnings": [],
    "series_catalog": [],
    "uploader_nonce": 0,
}
for _k, _v in _SESSION_DEFAULTS.items():
    st.session_state.setdefault(_k, _v)


local_folder = uploads.render_sidebar(APP_VERSION)

# --------------------------------------------------------------------------- #
# Load series from the catalog selection                                      #
# --------------------------------------------------------------------------- #


def _selected_catalog_entry() -> SeriesCatalogEntry | None:
    """The catalog entry the sidebar dropdown currently points at, if any."""
    catalog: list[SeriesCatalogEntry] = st.session_state.series_catalog
    chosen_uid: str | None = st.session_state.get("selected_series_uid")
    if not catalog or not chosen_uid:
        return None
    return next((e for e in catalog if e["uid"] == chosen_uid), None)


def _needs_reload(entry: SeriesCatalogEntry) -> bool:
    """True when the catalog entry isn't the one currently loaded."""
    return st.session_state.get("loaded_series_uid") != entry["uid"]


def _apply_loaded_series(loaded: DicomSeries, *, loaded_uid: str | None = None) -> None:
    """Store a freshly loaded series and reset everything derived from it."""
    st.session_state.series = loaded
    st.session_state.results = {}
    st.session_state.series_warnings = validate_series(loaded)
    if loaded_uid is not None:
        st.session_state.loaded_series_uid = loaded_uid


try:
    folder_path = local_folder.strip()
    catalog_entry = _selected_catalog_entry()
    if folder_path:
        _apply_loaded_series(load_series_from_folder(folder_path))
    elif catalog_entry is not None and _needs_reload(catalog_entry):
        _apply_loaded_series(
            load_series(catalog_entry["sources"]), loaded_uid=catalog_entry["uid"],
        )
except Exception as exc:
    uploads.show_load_error(exc)

series: DicomSeries | None = st.session_state.series

# Phantom-spec and field-strength selection happen on the Analysis tab so the
# inputs to the automated algorithms sit together.

# --------------------------------------------------------------------------- #
# Landing page when no series is loaded                                       #
# --------------------------------------------------------------------------- #

if series is None:
    landing.render()
    st.stop()

md = series.metadata

# --------------------------------------------------------------------------- #
# Analysis mode (axial protocol vs sagittal localizer)                        #
# --------------------------------------------------------------------------- #
analysis_mode: AnalysisMode = infer_analysis_mode(md)
test_order = SAGITTAL_TEST_ORDER if analysis_mode == "sagittal" else AXIAL_TEST_ORDER

# Clear results when switching analyses inside the same session (e.g. user
# picks a different series in the catalog and the mode flips).
if st.session_state.get("active_mode") != analysis_mode:
    results_view.clear_results()
    st.session_state.active_mode = analysis_mode

if analysis_mode == "sagittal":
    banner("<b>Sagittal localizer analysis</b> — single-image S-I length check.")
else:
    banner(
        f"<b>Axial selected-series analysis</b> — ACR {md.sequence} series "
        f"({md.n_slices} slices loaded). Results are not a combined accreditation determination."
    )

# --------------------------------------------------------------------------- #
# Metadata strip                                                              #
# --------------------------------------------------------------------------- #

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Patient / Phantom", md.patient_name or "—")
c2.metric("Scanner", f"{md.manufacturer} {md.model}".strip() or "—")
c3.metric("Field", f"{md.field_strength_t:.1f} T")
c4.metric("Pixel spacing", f"{md.pixel_spacing_mm[0]:.3f} mm")
c5.metric("Slices", str(md.n_slices))

st.caption(
    f"Series: {md.series_description or '—'} (#{md.series_number}) · {md.sequence} · "
    f"slice thickness {md.slice_thickness_mm:.2f} mm · "
    f"TR/TE {md.repetition_time_ms:.0f}/{md.echo_time_ms:.1f} ms · "
    f"study {md.study_date or '—'}"
)

# Non-fatal series warnings (wrong slice count, missing tags, etc.)
# Sagittal-localizer mode is single-image by design — suppress the "expected
# 11 slices" warning so it isn't shown as an error.
if st.session_state.series_warnings and analysis_mode == "axial":
    with st.expander(f"⚠️  Series warnings ({len(st.session_state.series_warnings)})",
                     expanded=True):
        for w in st.session_state.series_warnings:
            st.warning(w)

# --------------------------------------------------------------------------- #
# Tabs                                                                        #
# --------------------------------------------------------------------------- #

if analysis_mode == "axial":
    (tab_analysis, tab_manual, tab_viewer, tab_results,
     tab_validation, tab_history, tab_export) = st.tabs(
        ["Analysis", "Manual scoring", "Viewer", "Results",
         "Validation", "History", "Export"]
    )
    with tab_analysis:
        slice_mapping.render(series, test_order, analysis_mode)
    with tab_manual:
        manual_scoring.render(series, test_order, analysis_mode)
    with tab_results:
        st.subheader("Results")
        if not st.session_state.results:
            st.info(
                "Confirm slice roles and run automated tests on the "
                "**Analysis** tab first."
            )
        else:
            results_view.render(
                test_order, analysis_mode, series, key_prefix="results_tab",
            )
else:
    (tab_analysis, tab_viewer, tab_validation,
     tab_history, tab_export) = st.tabs(
        ["Analysis", "Viewer", "Validation", "History", "Export"]
    )
    with tab_analysis:
        sagittal_analysis.render(series, test_order)
        if not st.session_state.results:
            st.info("Press **Run S-I length test** above.")
        else:
            results_view.render(
                test_order, analysis_mode, series, key_prefix="results_tab",
            )

# Tabs shared between modes — both branches above bind these names.
with tab_viewer:
    viewer.render(series)
with tab_history:
    history.render()
with tab_validation:
    validation.render(series, test_order, analysis_mode)
with tab_export:
    export.render(series, test_order, analysis_mode, EXPORTS_DIR, APP_VERSION)
