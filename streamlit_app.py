"""MRIQA.ai — Streamlit entry point.

Run locally:
    streamlit run streamlit_app.py

Deployed: Streamlit Community Cloud points at this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# ---- make the `app/` package importable --------------------------------- #
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.io_dicom.dicom_loader import (              # noqa: E402
    DicomSeries, load_series, default_acr_slice_map,
    validate_series,
)
from app.qa_tests import (                              # noqa: E402
    AXIAL_TEST_ORDER, SAGITTAL_TEST_ORDER, AnalysisMode,
)
from app.qa_tests.base import TestResult  # noqa: E402
from app.ui import (                                  # noqa: E402
    analysis_inputs, auth, badges, export, history, manual_scoring,
    results_view, uploads, validation, viewer,
)
from app.ui.badges import normalize_img                # noqa: E402
from app.ui.banner import banner                       # noqa: E402

EXPORTS_DIR = _ROOT / "exports"
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

# series_catalog: accumulated series across upload batches; entries are
# the dicts returned by catalog_uploads ({uid, description, number,
# modality, n_files, sources}). Selected by selected_series_uid.
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

series: DicomSeries | None = st.session_state.series

if local_folder.strip():
    try:
        from app.io_dicom.dicom_loader import load_series_from_folder
        series = load_series_from_folder(local_folder.strip())
        st.session_state.series = series
        st.session_state.results = {}
        st.session_state.series_warnings = validate_series(series)
    except Exception as exc:
        uploads.show_load_error(exc)
elif st.session_state.series_catalog and st.session_state.get("selected_series_uid"):
    chosen_uid = st.session_state["selected_series_uid"]
    chosen = next((e for e in st.session_state.series_catalog
                   if e["uid"] == chosen_uid), None)
    if chosen and st.session_state.get("loaded_series_uid") != chosen_uid:
        try:
            series = load_series(chosen["sources"])
            st.session_state.series = series
            st.session_state.results = {}
            st.session_state.series_warnings = validate_series(series)
            st.session_state.loaded_series_uid = chosen_uid
        except Exception as exc:
            uploads.show_load_error(exc)
    else:
        series = st.session_state.series

# Phantom-spec and field-strength selection happen on the Analysis tab so the
# inputs to the automated algorithms sit together. See `_render_analysis_inputs`.

# --------------------------------------------------------------------------- #
# Landing page when no series is loaded                                       #
# --------------------------------------------------------------------------- #

if series is None:
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
                f"- **{s['datetime']}** · {s['scanner']} · "
                f"{s['sequence']} · {badges.status_badge(s['verdict'])} "
                f"(pass {s['counts']['PASS']} · fail {s['counts']['FAIL']} · "
                f"review {s['counts']['REVIEW']})",
                unsafe_allow_html=True,
            )
    st.stop()

md = series.metadata

# --------------------------------------------------------------------------- #
# Analysis mode (axial protocol vs sagittal localizer)                        #
# --------------------------------------------------------------------------- #
# A single-image series is treated as the sagittal-localizer S-I length
# analysis. Anything multi-slice runs the full axial protocol (the loader will
# already have warned on short series via validate_series).
analysis_mode: AnalysisMode = "sagittal" if md.n_slices == 1 else "axial"
test_order = SAGITTAL_TEST_ORDER if analysis_mode == "sagittal" else AXIAL_TEST_ORDER

# Clear results when switching analyses inside the same session (e.g. user
# picks a different series in the catalog and the mode flips).
if st.session_state.get("active_mode") != analysis_mode:
    st.session_state.results = {}
    st.session_state.pop("_visual_hcr_cache", None)
    st.session_state.pop("_visual_lcd_cache", None)
    st.session_state.active_mode = analysis_mode

if analysis_mode == "sagittal":
    banner("<b>Sagittal localizer analysis</b> — single-image S-I length check.")
else:
    banner(
        f"<b>Axial series analysis</b> — {len(AXIAL_TEST_ORDER)}-test ACR protocol "
        f"({md.n_slices} slices loaded)."
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
    tab_slices, tab_manual, tab_viewer, tab_results, tab_validation, tab_history, tab_export = st.tabs(
        ["Analysis", "Manual scoring", "Viewer", "Results",
         "Validation", "History", "Export"]
    )
else:
    tab_results, tab_viewer, tab_validation, tab_history, tab_export = st.tabs(
        ["Analysis", "Viewer", "Validation", "History", "Export"]
    )
    tab_slices = None
    tab_manual = None

# ----- Viewer ----------------------------------------------------------- #
with tab_viewer:
    viewer.render(series)



# ----- Analysis (axial: slice mapping + automated run) ----------------- #
if tab_slices is not None:
    with tab_slices:
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
        new_map = {}
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
            st.warning("Two or more ACR roles are mapped to the same physical slice. "
                       "This is unusual — confirm before running QA.")

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
            results: dict[str, TestResult] = dict(st.session_state.results)
            results.update(results_view.run_automated_tests(series, test_order))
            st.session_state.results = results
            st.rerun()

        # Show the results inline after a run, mirroring how the sagittal mode
        # surfaces them on the same tab that hosts the Run button.
        if st.session_state.results:
            st.divider()
            results_view.render(test_order, analysis_mode, series,
                                 key_prefix="slice_run_tab",
                                 scope="automated")

# ----- Results / sagittal Analysis -------------------------------------- #
with tab_results:
    if analysis_mode == "axial":
        st.subheader("Results")

    # Sagittal mode has no separate slice-mapping step — the run trigger plus
    # the algorithm inputs live here on the Analysis tab.
    if analysis_mode == "sagittal":
        st.subheader("Analysis inputs")
        st.caption(
            "Everything above the **Run S-I length test** button is an input "
            "to the algorithm. The dropdowns are pre-selected from the loaded "
            "series — change them only if the defaults are wrong."
        )
        analysis_inputs.render(series, key_prefix="sagittal_inputs",
                                show_sequence=False)

        st.divider()
        st.subheader("Sagittal image")
        st.caption(
            "The S-I length is measured on a single sagittal scout. The "
            "selector mirrors the axial slice-mapping picker for consistency; "
            "with a 1-image upload it is trivially 1 of 1."
        )
        _sag_cols = st.columns(4)
        with _sag_cols[0]:
            sag_idx = st.number_input(
                "Sagittal image → physical index",
                min_value=1, max_value=max(1, md.n_slices),
                value=1, step=1, key="sagittal_image_index",
            )
            _sag_preview = normalize_img(series.pixel_array[int(sag_idx) - 1])
            st.image(_sag_preview, caption=f"Physical slice {int(sag_idx)}", width=180)

        st.divider()
        st.subheader("Run")
        st.caption(
            f"Measures the phantom's superior-inferior length on the sagittal "
            f"scout against the spec nominal "
            f"({series.spec.si_length_mm:.0f} mm ± {series.spec.length_tolerance_mm:.0f} mm)."
        )
        if st.button("Run S-I length test", type="primary"):
            results: dict[str, TestResult] = dict(st.session_state.results)
            for t in test_order:
                try:
                    res = t.runner.run(series, spec=series.spec)
                except Exception as e:
                    res = TestResult(test_id=t.id, test_name=t.label, automated=True,
                                     passed=None, error=str(e))
                results[t.id] = res
            st.session_state.results = results
            st.rerun()

    if not st.session_state.results:
        if analysis_mode == "axial":
            st.info("Confirm slice roles and run automated tests on the "
                    "**Analysis** tab first.")
        else:
            st.info("Press **Run S-I length test** above.")
    else:
        results_view.render(test_order, analysis_mode, series,
                             key_prefix="results_tab")

# ----- Manual scoring (axial only) ------------------------------------- #
if tab_manual is not None:
    with tab_manual:
        manual_scoring.render(series, test_order, analysis_mode)

# ----- History (in-browser-session) ------------------------------------- #
with tab_history:
    history.render()

# ----- Validation (testing mode) --------------------------------------- #
with tab_validation:
    validation.render(series, test_order, analysis_mode)


# ----- Export ----------------------------------------------------------- #
with tab_export:
    export.render(series, test_order, EXPORTS_DIR, APP_VERSION)
