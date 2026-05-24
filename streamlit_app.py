"""MRIQA.ai — Streamlit entry point.

Run locally:
    streamlit run streamlit_app.py

Deployed: Streamlit Community Cloud points at this file.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import streamlit as st

# ---- make the `app/` package importable --------------------------------- #
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.io_dicom.dicom_loader import (              # noqa: E402
    DicomSeries, DicomLoadError, load_series, default_acr_slice_map,
    validate_series,
)
from app.qa_tests import AXIAL_TEST_ORDER, SAGITTAL_TEST_ORDER  # noqa: E402
from app.qa_tests import high_contrast_resolution, low_contrast_detectability  # noqa: E402
from app.qa_tests.base import TestResult, verdict_of  # noqa: E402
from app.utils.phantom import detect_phantom_spec    # noqa: E402
from app.utils.phantom_spec import PHANTOMS, LARGE   # noqa: E402
from app.ui import auth, viewer, history, export, uploads, validation  # noqa: E402
from app.ui.badges import (                          # noqa: E402
    normalize_img as _normalize_img,
    status_badge as _status_badge,
    confidence_badge as _confidence_badge,
)
from app.ui.history import snapshot_run as _snapshot_run  # noqa: E402

EXPORTS_DIR = _ROOT / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)
APP_VERSION = "0.2.0-mvp"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _switch_tab(label: str) -> None:
    """Programmatically activate the st.tabs tab whose label starts with
    `label`. Streamlit has no API for this, so we inject a tiny script that
    walks the parent document for buttons carrying the ARIA `role="tab"`
    contract used by st.tabs and clicks the first match. Fragile against
    Streamlit DOM changes but the ARIA role is the stable target."""
    st.iframe(
        f"""
        <script>
        (function() {{
          const click = () => {{
            const doc = window.parent.document;
            const buttons = doc.querySelectorAll('button[role="tab"]');
            for (const b of buttons) {{
              const text = (b.innerText || b.textContent || '').trim();
              if (text.startsWith({label!r})) {{ b.click(); return; }}
            }}
          }};
          setTimeout(click, 50);
        }})();
        </script>
        """,
        # st.iframe's height validator rejects 0 — the smallest legal value is
        # 1px, which leaves a sliver that's essentially invisible. The iframe
        # body is just a <script> tag with no rendered content.
        height=1,
    )


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
# Sidebar — uploader + guidance                                               #
# --------------------------------------------------------------------------- #

_PHANTOM_OPTIONS = [(s.short_name, s.name) for s in PHANTOMS.values()]


# --------------------------------------------------------------------------- #
# Session state init                                                          #
# --------------------------------------------------------------------------- #

if "series" not in st.session_state:
    st.session_state.series = None
if "results" not in st.session_state:
    st.session_state.results = {}
if "history" not in st.session_state:
    st.session_state.history = []           # list[snapshot]
if "validation_log" not in st.session_state:
    st.session_state.validation_log = []    # list[dict]
if "series_warnings" not in st.session_state:
    st.session_state.series_warnings = []   # non-fatal warnings from validate_series
if "series_catalog" not in st.session_state:
    # Accumulated series across all upload batches in this session. Each entry
    # is the dict returned by _catalog_uploads — {uid, description, number,
    # modality, n_files, sources}. Selected by `selected_series_uid`.
    st.session_state.series_catalog = []
if "uploader_nonce" not in st.session_state:
    # Bumping the nonce re-mounts the file_uploader widget as a fresh, empty
    # drop zone — that's how we hide the persistent "1 file uploaded" list.
    st.session_state.uploader_nonce = 0


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
                f"{s['sequence']} · {_status_badge(s['verdict'])} "
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
analysis_mode = "sagittal" if md.n_slices == 1 else "axial"
test_order = SAGITTAL_TEST_ORDER if analysis_mode == "sagittal" else AXIAL_TEST_ORDER

# Clear results when switching analyses inside the same session (e.g. user
# picks a different series in the catalog and the mode flips).
if st.session_state.get("active_mode") != analysis_mode:
    st.session_state.results = {}
    st.session_state.pop("_visual_hcr_cache", None)
    st.session_state.pop("_visual_lcd_cache", None)
    st.session_state.active_mode = analysis_mode

if analysis_mode == "sagittal":
    st.markdown(
        "<div class='mri-banner mri-banner-dash'>"
        "<b>Sagittal localizer analysis</b> — single-image S-I length check."
        "</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        "<div class='mri-banner mri-banner-dash'>"
        f"<b>Axial series analysis</b> — {len(AXIAL_TEST_ORDER)}-test ACR protocol "
        f"({md.n_slices} slices loaded)."
        "</div>",
        unsafe_allow_html=True,
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

# Honor a queued tab-switch request (set by the series-picker on_change).
_pending = st.session_state.pop("pending_tab_switch", None)
if _pending:
    _switch_tab(_pending)

# ----- Viewer ----------------------------------------------------------- #
with tab_viewer:
    viewer.render(series)

_VISUAL_TEST_IDS = {"high_contrast_resolution", "low_contrast_detectability"}


def _detect_sequence_type(tr_ms: float, te_ms: float) -> str:
    """Classify an ACR phantom acquisition as T1 or T2 from TR/TE.

    The ACR axial protocol nominates TR≈500 / TE≈20 for T1 and
    TR≈2000 / TE≈80 for T2, so TE alone is a clean separator. TR is
    used as a tiebreaker when TE is missing.
    """
    if te_ms and te_ms > 0:
        return "T2" if te_ms >= 40.0 else "T1"
    if tr_ms and tr_ms > 0:
        return "T2" if tr_ms >= 1000.0 else "T1"
    return "T1"


def _render_analysis_inputs(series, *, key_prefix: str, show_sequence: bool = True):
    """Render the phantom + field-strength (+ sequence, axial only) inputs at
    the top of an Analysis tab and apply them to `series` in place. Defaults
    are detected per-series — phantom from the segmented left-right width
    (robust to A-P bubbles; also valid on a sagittal scout where the axial
    circumference runs L-R), field strength from the DICOM tag snapped to
    1.5 / 3.0 T, sequence from TR / TE.

    The widget keys are suffixed with the loaded series UID so picking a
    different series re-mounts the dropdowns with fresh detected defaults
    via `index=`. User overrides within the same series persist because the
    key stays stable across reruns of that series. This avoids the Streamlit
    quirk where pre-render assignment to `st.session_state[widget_key]` is
    not honored once the widget has already been instantiated under that key
    in a prior run.

    `key_prefix` keeps the keys unique when the same controls render on more
    than one tab body within a single run.
    """
    series_uid = st.session_state.get("loaded_series_uid") or str(id(series))
    series_tag = "".join(c if c.isalnum() else "_" for c in str(series_uid))[-32:]

    idx0 = series.acr_slice_map.get(1, 0)
    spec_auto, _ = detect_phantom_spec(
        series.pixel_array[idx0], series.metadata.pixel_spacing_mm,
    )
    detected_phantom = spec_auto.short_name
    b0 = series.metadata.field_strength_t
    detected_field = "3.0 T" if b0 >= 2.0 else "1.5 T"
    detected_sequence = _detect_sequence_type(
        series.metadata.repetition_time_ms, series.metadata.echo_time_ms,
    )

    phantom_options = [opt[0] for opt in _PHANTOM_OPTIONS]
    field_options = ["1.5 T", "3.0 T"]
    sequence_options = ["T1", "T2"]

    cols = st.columns(3 if show_sequence else 2)
    with cols[0]:
        choice = st.selectbox(
            "ACR phantom model",
            options=phantom_options,
            format_func=lambda k: dict(_PHANTOM_OPTIONS)[k],
            index=phantom_options.index(detected_phantom),
            key=f"{key_prefix}_phantom_{series_tag}",
            help="Pre-selected from the phantom's segmented left-right width. "
                 "Large = 190 mm Ø / 148 mm S-I; Medium = 165 mm Ø / 134 mm S-I.",
        )
    with cols[1]:
        fld = st.selectbox(
            "Scanner field strength",
            options=field_options,
            index=field_options.index(detected_field),
            key=f"{key_prefix}_field_{series_tag}",
            help="Pre-selected from the DICOM MagneticFieldStrength tag "
                 "(snapped to the nearest of 1.5 / 3.0 T).",
        )
    if show_sequence:
        with cols[2]:
            seq = st.selectbox(
                "Axial sequence",
                options=sequence_options,
                index=sequence_options.index(detected_sequence),
                key=f"{key_prefix}_sequence_{series_tag}",
                help="Pre-selected from TR / TE (T2 when TE ≥ 40 ms). At 1.5 T "
                     "the ACR LCD threshold is sequence-dependent: 30 spokes "
                     "for T1, 25 for T2.",
            )
        series.metadata.sequence = seq

    series.spec = PHANTOMS.get(choice, LARGE)
    series.metadata.field_strength_t = 1.5 if fld == "1.5 T" else 3.0


def _render_results_view(test_order, analysis_mode, series, *,
                         key_prefix: str, scope: str = "all"):
    """Render the verdict banner + summary table + per-test details, and
    (when `scope="all"`) a save-to-history button. `scope` controls which
    subset of tests is shown:

      - ``"automated"`` — non-visual tests only. Used inline on the Analysis
        tab so the user sees what the automated run produced without empty
        REVIEW rows for un-scored visual tests.
      - ``"manual"`` — visual tests only. Used inline on the Manual scoring
        tab so the saved HCR / LCD rows appear right after Save.
      - ``"all"`` — every test. Used on the Results tab and on the sagittal
        Analysis tab (which IS the only results surface in sagittal mode).

    The verdict is computed over the displayed subset, so the Analysis tab
    can show PASS without being held back by un-scored visuals. The
    save-to-history button only renders for ``scope="all"`` to keep the
    primary "I'm done" action on Results.
    """
    if scope == "automated":
        displayed_order = [t for t in test_order if t[0] not in _VISUAL_TEST_IDS]
    elif scope == "manual":
        displayed_order = [t for t in test_order if t[0] in _VISUAL_TEST_IDS]
    else:
        displayed_order = list(test_order)

    displayed_ids = {tid for tid, _, _ in displayed_order}
    displayed_results = {
        tid: r for tid, r in st.session_state.results.items() if tid in displayed_ids
    }

    # Pending-visual nudge: useful whenever the view spans the manual subset
    # ("automated" → your next step is Manual; "all" → you still have manual
    # to score). On the manual tab itself the hint would be redundant.
    if analysis_mode == "axial" and scope != "manual":
        visual_pending = [
            tid for tid in _VISUAL_TEST_IDS
            if tid not in st.session_state.results
        ]
        automated_failed = any(
            r.status_text() == "FAIL"
            for tid, r in st.session_state.results.items()
            if tid not in _VISUAL_TEST_IDS
        )
        if visual_pending and not automated_failed:
            st.info(
                "Automated tests are in. Visual scoring (high-contrast "
                "resolution + low-contrast detectability) is still pending — "
                "open the **Manual scoring** tab to score them when ready."
            )
        elif visual_pending and automated_failed:
            st.warning(
                "One or more automated tests **failed**. Manual scoring is "
                "usually not worth doing until the underlying acquisition / "
                "calibration issue is resolved — but it's available on the "
                "**Manual scoring** tab if you need a complete report."
            )

    verdict, counts = verdict_of(displayed_results.values())
    verdict_cls = {
        "PASS": "PASS", "FAIL": "FAIL", "REVIEW": "REVIEW",
        "ERROR": "ERROR", "—": "dash",
    }[verdict]
    st.markdown(
        f"""
        <div class='mri-banner mri-banner-{verdict_cls}'>
          <div style='font-size:1.05em; font-weight:600;'>
            Overall verdict: {_status_badge(verdict)}
          </div>
          <div class='mri-small' style='margin-top:4px;'>
            {counts['PASS']} pass · {counts['FAIL']} fail · {counts['REVIEW']} review · {counts['ERROR']} error
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rows = []
    for tid, _, _ in displayed_order:
        r: TestResult | None = st.session_state.results.get(tid)
        if r is None:
            rows.append({"Test": tid, "Status": "—", "Confidence": "—", "Detail": ""})
            continue
        key = r.measurements[0] if r.measurements else None
        rows.append({
            "Test": r.test_name,
            "Status": r.status_text(),
            "Confidence": r.confidence_label(),
            "Detail": (f"{key.label}: {key.value} {key.unit}" if key else "") + (
                f" · spec {key.spec}" if key and key.spec else ""
            ),
            "Error": r.error or "",
        })
    st.dataframe(rows, hide_index=True, width="stretch")

    st.markdown("### Per-test details")
    for tid, label, _ in displayed_order:
        r: TestResult | None = st.session_state.results.get(tid)
        if r is None:
            continue
        title = f"{r.test_name} — {r.status_text()}"
        with st.expander(title, expanded=(r.status_text() in ("FAIL", "ERROR") or r.confidence != "high")):
            st.markdown(
                f"{_status_badge(r.status_text())} &nbsp; {_confidence_badge(r.confidence)}",
                unsafe_allow_html=True,
            )
            if r.warnings:
                for w in r.warnings:
                    st.warning(w)
            if r.error:
                st.error(r.error)
            if r.notes:
                st.caption(r.notes)
            if r.measurements:
                st.dataframe(
                    [{"Measurement": m.label, "Value": m.value, "Unit": m.unit,
                      "Spec": m.spec,
                      "Pass": "" if m.passed is None else ("✓" if m.passed else "✗")}
                     for m in r.measurements],
                    hide_index=True, width="stretch",
                )
            if r.annotated_images:
                img_cols = st.columns(min(2, len(r.annotated_images)))
                for i, (cap, im) in enumerate(r.annotated_images):
                    with img_cols[i % len(img_cols)]:
                        st.image(im, caption=cap, width="stretch")

    if scope == "all":
        st.divider()
        if st.button("Save this run to History", key=f"{key_prefix}_save_history"):
            snap = _snapshot_run(series, dict(st.session_state.results))
            st.session_state.history.append(snap)
            st.success(f"Snapshot saved — {len(st.session_state.history)} run(s) in this session.")


def _run_automated_tests(series, test_order):
    """Run every test in test_order that is not a manual/visual scoring test.

    Manual tests (HCR, LCD) live on the Manual scoring tab and are not
    touched here. Returns a dict ready to merge into st.session_state.results.
    """
    out: dict[str, TestResult] = {}
    automated = [
        (tid, label, mod) for (tid, label, mod) in test_order
        if tid not in _VISUAL_TEST_IDS
    ]
    prog = st.progress(0, text="Running automated tests...")
    for i, (tid, label, mod) in enumerate(automated):
        prog.progress((i + 1) / max(1, len(automated)),
                      text=f"Running {label}...")
        try:
            out[tid] = mod.run(series, spec=series.spec)
        except Exception as e:
            out[tid] = TestResult(
                test_id=tid, test_name=label, automated=True,
                passed=None, error=str(e),
            )
    prog.empty()
    return out


# ----- Analysis (axial: slice mapping + automated run) ----------------- #
if tab_slices is not None:
    with tab_slices:
        st.subheader("Analysis inputs")
        st.caption(
            "Everything above the **Run all automated tests** button is an "
            "input to the algorithms. The dropdowns are pre-selected from the "
            "loaded series — change them only if the defaults are wrong."
        )
        _render_analysis_inputs(series, key_prefix="axial_inputs")

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
                preview = _normalize_img(series.pixel_array[int(v) - 1])
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
            results.update(_run_automated_tests(series, test_order))
            st.session_state.results = results
            st.rerun()

        # Show the results inline after a run, mirroring how the sagittal mode
        # surfaces them on the same tab that hosts the Run button.
        if st.session_state.results:
            st.divider()
            _render_results_view(test_order, analysis_mode, series,
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
        _render_analysis_inputs(series, key_prefix="sagittal_inputs",
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
            _sag_preview = _normalize_img(series.pixel_array[int(sag_idx) - 1])
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
            for tid, label, mod in test_order:
                try:
                    res = mod.run(series, spec=series.spec)
                except Exception as e:
                    res = TestResult(test_id=tid, test_name=label, automated=True,
                                     passed=None, error=str(e))
                results[tid] = res
            st.session_state.results = results
            st.rerun()

    if not st.session_state.results:
        if analysis_mode == "axial":
            st.info("Confirm slice roles and run automated tests on the "
                    "**Analysis** tab first.")
        else:
            st.info("Press **Run S-I length test** above.")
    else:
        _render_results_view(test_order, analysis_mode, series,
                             key_prefix="results_tab")

# ----- Manual scoring (axial only) ------------------------------------- #
if tab_manual is not None:
    with tab_manual:
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
            if tid not in _VISUAL_TEST_IDS
        }
        if automated_results and any(r.status_text() == "FAIL" for r in automated_results.values()):
            st.warning(
                "One or more automated tests **failed**. Manual scoring is "
                "usually a waste of time on a series with a clear acquisition "
                "or calibration problem — fix the upstream issue first unless "
                "you need a complete report."
            )

        st.markdown("### High-contrast resolution")
        st.caption("On slice 1, look at the UL and LR hole arrays in the zoomed crops below.")
        _series_key = id(series)
        _hcr_existing = st.session_state.results.get("high_contrast_resolution")
        if _hcr_existing is not None and _hcr_existing.annotated_images:
            _hcr_images = _hcr_existing.annotated_images
        else:
            _hcr_cache = st.session_state.get("_visual_hcr_cache")
            if _hcr_cache is None or _hcr_cache[0] != _series_key:
                _hcr_images = high_contrast_resolution.run(series, spec=series.spec).annotated_images
                st.session_state["_visual_hcr_cache"] = (_series_key, _hcr_images)
            else:
                _hcr_images = _hcr_cache[1]
        for _cap, _im in _hcr_images:
            st.image(_im, caption=_cap, width="stretch")
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
        threshold = cspec.selectbox("Required smallest row (mm)", res_sizes, index=res_default_idx)
        ul = cul.selectbox("UL smallest resolvable",
                           [None, *res_sizes],
                           format_func=lambda x: "—" if x is None else f"{x} mm")
        lr = clr.selectbox("LR smallest resolvable",
                           [None, *res_sizes],
                           format_func=lambda x: "—" if x is None else f"{x} mm")
        if st.button("Save resolution scoring"):
            res = high_contrast_resolution.run(
                series, spec=series.spec,
                user_input={"UL": ul, "LR": lr, "spec": threshold},
            )
            st.session_state.results["high_contrast_resolution"] = res
            st.success("Saved.")

        st.divider()

        lcd_slices = series.spec.lcd_slices
        lcd_range_label = f"{lcd_slices[0]}–{lcd_slices[-1]}"
        st.markdown("### Low-contrast object detectability")
        st.caption(f"Count complete spokes visible on each of slices {lcd_range_label}.")
        _lcd_existing = st.session_state.results.get("low_contrast_detectability")
        if _lcd_existing is not None and _lcd_existing.annotated_images:
            _lcd_images = _lcd_existing.annotated_images
        else:
            _lcd_cache = st.session_state.get("_visual_lcd_cache")
            if _lcd_cache is None or _lcd_cache[0] != _series_key:
                _lcd_images = low_contrast_detectability.run(series, spec=series.spec).annotated_images
                st.session_state["_visual_lcd_cache"] = (_series_key, _lcd_images)
            else:
                _lcd_images = _lcd_cache[1]
        if _lcd_images:
            _img_cols = st.columns(min(len(_lcd_images), 4))
            for i, (_cap, _im) in enumerate(_lcd_images):
                with _img_cols[i % len(_img_cols)]:
                    st.image(_im, caption=_cap, width="stretch")
        with st.form("lcd_scoring_form", clear_on_submit=False):
            cs = st.columns(len(lcd_slices))
            spoke_counts: dict[int, int] = {}
            for col, s in zip(cs, lcd_slices):
                with col:
                    spoke_counts[s] = st.number_input(
                        f"Slice {s} spokes", min_value=0, max_value=10, value=0, step=1,
                        key=f"lcd_spokes_{s}",
                    )
            _lcd_submitted = st.form_submit_button("Save LCD scoring")
        if _lcd_submitted:
            res = low_contrast_detectability.run(
                series, spec=series.spec, user_input=spoke_counts,
            )
            st.session_state.results["low_contrast_detectability"] = res
            st.success("Saved.")

        # Show just the manual results inline once at least one visual test
        # has been scored. The full automated+manual roll-up lives on Results.
        manual_done = any(
            tid in _VISUAL_TEST_IDS for tid in st.session_state.results
        )
        if manual_done:
            st.divider()
            _render_results_view(test_order, analysis_mode, series,
                                 key_prefix="manual_tab",
                                 scope="manual")

# ----- History (in-browser-session) ------------------------------------- #
with tab_history:
    history.render()

# ----- Validation (testing mode) --------------------------------------- #
with tab_validation:
    validation.render(series, test_order, analysis_mode)


# ----- Export ----------------------------------------------------------- #
with tab_export:
    export.render(series, test_order, EXPORTS_DIR, APP_VERSION)
