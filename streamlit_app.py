"""MRIQA.ai — Streamlit entry point.

Run locally:
    streamlit run streamlit_app.py

Deployed: Streamlit Community Cloud points at this file.
"""

from __future__ import annotations

import hmac
import io
import sys
import zipfile
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
from app.qa_tests import TEST_ORDER                  # noqa: E402
from app.qa_tests import high_contrast_resolution, low_contrast_detectability  # noqa: E402
from app.qa_tests.base import TestResult             # noqa: E402
from app.reporting.csv_report import write_csv       # noqa: E402
from app.reporting.pdf_report import write_pdf       # noqa: E402
from app.utils.phantom_spec import PHANTOMS, LARGE   # noqa: E402

EXPORTS_DIR = _ROOT / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)
APP_VERSION = "0.2.0-mvp"


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _configured_password():
    """Return the shared password from Streamlit secrets, or None if unset."""
    try:
        return st.secrets.get("password")
    except Exception:
        return None


def check_password() -> bool:
    """Gate the app behind a shared password stored in Streamlit secrets.

    Behaviour:
      * If no password is configured, the app stays open but shows a loud
        warning (so the admin is never locked out during setup).
      * If a password is configured, visitors must enter it once per session.
    """
    configured = _configured_password()
    if not configured:
        # No password set (e.g. local development). Open access, slim notice.
        st.caption(
            "🔓 Open access (no password set). To require a login on the deployed "
            "app, add a `password` secret in Streamlit Cloud — see DEPLOY.md."
        )
        return True

    if st.session_state.get("auth_ok", False):
        return True

    def _verify():
        entered = st.session_state.get("auth_pw", "")
        if hmac.compare_digest(str(entered), str(configured)):
            st.session_state["auth_ok"] = True
            st.session_state.pop("auth_pw", None)
        else:
            st.session_state["auth_ok"] = False

    st.markdown("#### Sign in")
    st.text_input("Password", type="password", key="auth_pw", on_change=_verify)
    if st.session_state.get("auth_ok") is False:
        st.error("Incorrect password. Please try again.")
    st.caption(
        "Access is restricted to pilot testers. Contact the app owner for the password. "
        "Please upload anonymized ACR phantom DICOMs only — no patient data."
    )
    return False


def _normalize_img(img: np.ndarray, wl: float | None = None, ww: float | None = None) -> np.ndarray:
    img = img.astype(np.float32)
    if img.size == 0 or not np.isfinite(img).any():
        return np.zeros((1, 1), dtype=np.uint8)
    if wl is None or ww is None or ww <= 0:
        p2, p98 = np.percentile(img, (2, 98))
        if p98 - p2 < 1e-6:
            p2, p98 = float(img.min()), float(img.max() + 1)
        out = np.clip((img - p2) / (p98 - p2), 0, 1)
    else:
        lo, hi = wl - ww / 2, wl + ww / 2
        out = np.clip((img - lo) / (hi - lo + 1e-6), 0, 1)
    return (out * 255).astype(np.uint8)


def _expand_uploads(uploaded_files) -> list:
    sources = []
    for uf in uploaded_files:
        name = uf.name.lower()
        data = uf.read()
        if name.endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    nlow = info.filename.lower()
                    if "__macosx" in nlow or nlow.endswith(".ds_store"):
                        continue
                    sources.append(z.read(info))
            except zipfile.BadZipFile:
                st.error(f"Could not read zip: {uf.name}")
        else:
            sources.append(data)
    return sources


def _status_badge(status: str) -> str:
    """Return a markdown-friendly colored badge for a test status."""
    color = {
        "PASS": "#1e8e3e",
        "FAIL": "#d93025",
        "REVIEW": "#b06000",
        "ERROR": "#666666",
        "—": "#cccccc",
    }.get(status, "#cccccc")
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:0.78em;font-weight:600;letter-spacing:0.5px;'>"
        f"{status}</span>"
    )


def _confidence_badge(conf: str) -> str:
    """Return a markdown-friendly colored badge for detection confidence."""
    color, label = {
        "high":   ("#1e8e3e", "HIGH"),
        "medium": ("#b06000", "MEDIUM"),
        "low":    ("#d93025", "LOW"),
    }.get(conf, ("#cccccc", "—"))
    return (
        f"<span style='background:white;color:{color};border:1px solid {color};"
        f"padding:1px 8px;border-radius:10px;font-size:0.74em;font-weight:600;"
        f"letter-spacing:0.5px;'>confidence: {label}</span>"
    )


def _overall_status(results: dict[str, TestResult]) -> tuple[str, dict]:
    """Roll up per-test statuses into an overall verdict and counts."""
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
    for r in results.values():
        counts[r.status_text()] = counts.get(r.status_text(), 0) + 1
    if counts["FAIL"] > 0:
        verdict = "FAIL"
    elif counts["ERROR"] > 0:
        verdict = "ERROR"
    elif counts["REVIEW"] > 0:
        verdict = "REVIEW"
    elif counts["PASS"] > 0:
        verdict = "PASS"
    else:
        verdict = "—"
    return verdict, counts


def _snapshot_run(series: DicomSeries, results: dict[str, TestResult]) -> dict:
    """Build a serializable-ish snapshot of a completed run for in-session history."""
    md = series.metadata
    verdict, counts = _overall_status(results)
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
        "results": results,    # kept in-memory only; not serialized to disk
        "series": series,
    }


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
if not check_password():
    st.stop()

st.caption(
    "Decision-support tool for medical physicists. "
    "**Not a medical device. Not for diagnostic use.** "
    "Thresholds from the ACR Large and Medium Phantom Test Guidance (Oct 2022)."
)

# --------------------------------------------------------------------------- #
# Sidebar — uploader + guidance                                               #
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.header("Upload phantom DICOMs")
    st.markdown(
        "**Only upload ACR phantom scans.** Do not upload patient images. "
        "Free-tier deployments process files in memory; nothing is stored "
        "between sessions, but de-identify before uploading anyway."
    )
    st.markdown(
        "<div class='mri-small'>"
        "Expected input: a single T1 or T2 ACR phantom series — "
        "11 axial slices, 250&nbsp;mm FOV, 5&nbsp;mm thickness."
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    st.markdown("**Phantom**")
    _phantom_options = [(s.short_name, s.name) for s in PHANTOMS.values()]
    phantom_choice = st.selectbox(
        "ACR phantom model",
        options=[opt[0] for opt in _phantom_options],
        format_func=lambda k: dict(_phantom_options)[k],
        index=[i for i, (k, _) in enumerate(_phantom_options) if k == LARGE.short_name][0],
        help="Selects the geometric and pass/fail thresholds. Large = 190 mm Ø / "
             "148 mm S-I; Medium = 165 mm Ø / 134 mm S-I.",
    )

    uploaded = st.file_uploader(
        "Drop a .zip of the series, or select .dcm files",
        type=None,
        accept_multiple_files=True,
        help="Accepts a folder zip or individual .dcm files.",
    )

    st.markdown("**Optional: sagittal localizer**")
    _selected_spec = PHANTOMS.get(phantom_choice, LARGE)
    st.caption(
        "Upload the sagittal scout to enable the geometric-accuracy "
        f"superior-inferior length ({_selected_spec.si_length_mm:.0f} mm) check, "
        "which cannot be measured on an axial slice."
    )
    uploaded_loc = st.file_uploader(
        "Localizer (.zip or .dcm)",
        type=None,
        accept_multiple_files=True,
        key="loc_uploader",
        help="The sagittal localizer/scout series.",
    )

    st.markdown("**Scanner field strength**")
    field_choice = st.selectbox(
        "Used for the PIU / low-contrast action limits",
        ["Auto (from DICOM)", "1.5 T", "3.0 T"],
        index=0,
        help="If the DICOM is missing the MagneticFieldStrength tag (shows B0 = 0.0 T), "
             "set it here so the correct ACR thresholds apply.",
    )

    with st.expander("Advanced — load from a local folder"):
        local_folder = st.text_input(
            "Path to a folder of .dcm files",
            value="",
            help="Only works when running the app locally, not on Streamlit Cloud.",
        )

    if st.session_state.get("series") is not None:
        st.divider()
        if st.button("Reset / load a new series", use_container_width=True):
            for k in ("series", "results", "localizer", "series_warnings",
                      "view_wl", "view_ww"):
                st.session_state.pop(k, None)
            st.rerun()

    st.divider()
    st.caption(f"App version {APP_VERSION}")

# --------------------------------------------------------------------------- #
# Load series                                                                 #
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
if "localizer" not in st.session_state:
    st.session_state.localizer = None       # optional sagittal localizer series

series: DicomSeries | None = st.session_state.series

def _show_load_error(exc: Exception):
    if isinstance(exc, DicomLoadError):
        st.sidebar.error(str(exc))
        if exc.tip:
            st.sidebar.info(f"**Tip:** {exc.tip}")
    else:
        st.sidebar.error(f"Failed to load DICOMs: {exc}")


if local_folder.strip():
    try:
        from app.io_dicom.dicom_loader import load_series_from_folder
        series = load_series_from_folder(local_folder.strip())
        st.session_state.series = series
        st.session_state.results = {}
        st.session_state.series_warnings = validate_series(series)
    except Exception as exc:
        _show_load_error(exc)
elif uploaded:
    try:
        sources = _expand_uploads(uploaded)
        series = load_series(sources)
        st.session_state.series = series
        st.session_state.results = {}
        st.session_state.series_warnings = validate_series(series)
    except Exception as exc:
        _show_load_error(exc)

# Optional localizer (loaded independently; attached to the main series below)
if uploaded_loc:
    try:
        loc_sources = _expand_uploads(uploaded_loc)
        st.session_state.localizer = load_series(loc_sources)
    except Exception as exc:
        st.sidebar.warning(f"Could not load localizer: {exc}")
        st.session_state.localizer = None

# Attach the localizer to the active series so geometric accuracy can use it
if series is not None:
    series.localizer = st.session_state.get("localizer")
    # Apply the selected phantom spec. Loader attaches LARGE by default; this
    # lets the user pick Medium without having to re-upload. Note: Large and
    # Medium share the same 11-slice ACR mapping, so series.acr_slice_map does
    # not need to be recomputed. If a future spec introduces a different
    # protocol, recompute via default_acr_slice_map(n_slices, new_spec) here —
    # but only when the user has not customized the mapping in the Slice
    # Mapping tab.
    series.spec = PHANTOMS.get(phantom_choice, LARGE)
    # Apply a manual field-strength override (used for PIU / low-contrast limits)
    # when the DICOM tag is missing or the user wants to force a value.
    if field_choice == "1.5 T":
        series.metadata.field_strength_t = 1.5
    elif field_choice == "3.0 T":
        series.metadata.field_strength_t = 3.0
    # "Auto" leaves the DICOM-derived value as-is.

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
            "into the sidebar. Both T1 and T2 series work."
        )
    with c2:
        st.markdown("### 2. Confirm")
        st.markdown(
            "Auto-detected ACR slice roles (1, 5, 7, 11) are shown so you can "
            "verify or override them before analysis."
        )
    with c3:
        st.markdown("### 3. Run + Report")
        st.markdown(
            "Five ACR tests run automatically; two are visual scoring tests "
            "with zoom-in views. Export a PDF + CSV when done."
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
if st.session_state.series_warnings:
    with st.expander(f"⚠️  Series warnings ({len(st.session_state.series_warnings)})",
                     expanded=True):
        for w in st.session_state.series_warnings:
            st.warning(w)

# --------------------------------------------------------------------------- #
# Tabs                                                                        #
# --------------------------------------------------------------------------- #

tab_viewer, tab_slices, tab_run, tab_results, tab_history, tab_validation, tab_export = st.tabs(
    ["Viewer", "Slice mapping", "Run QA", "Results", "History", "Validation", "Export"]
)

# ----- Viewer ----------------------------------------------------------- #
with tab_viewer:
    st.subheader("Slice viewer")
    n = md.n_slices

    # Volume-wide auto window so the same level/width applies to ALL slices
    # (like a standard DICOM viewer) instead of resetting per slice.
    vol = series.pixel_array
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
        st.button("Auto", on_click=_reset_window, use_container_width=True,
                  help="Reset window to the auto level/width for this series.")
    st.caption("Window level/width applies to all slices as you scroll.")

    img = _normalize_img(vol[idx - 1], wl=st.session_state.view_wl, ww=st.session_state.view_ww)
    st.image(img, caption=f"Slice {idx} of {n}", width=560)

# ----- Slice mapping ---------------------------------------------------- #
with tab_slices:
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

# ----- Run QA ----------------------------------------------------------- #
with tab_run:
    st.subheader("Run ACR QA tests")
    st.write(
        "Five automated tests run server-side. Two visual tests "
        "(high-contrast resolution, low-contrast detectability) need your input."
    )

    if st.button("Run all automated tests", type="primary"):
        results: dict[str, TestResult] = dict(st.session_state.results)
        prog = st.progress(0, text="Running QA...")
        for i, (tid, label, mod) in enumerate(TEST_ORDER):
            prog.progress((i + 1) / len(TEST_ORDER), text=f"Running {label}...")
            is_user_test = mod in (high_contrast_resolution, low_contrast_detectability)
            try:
                if is_user_test and tid in results and results[tid].measurements:
                    continue
                res = mod.run(series, spec=series.spec)
            except Exception as e:
                res = TestResult(test_id=tid, test_name=label, automated=not is_user_test,
                                 passed=None, error=str(e))
            results[tid] = res
        st.session_state.results = results
        prog.empty()
        st.success("Done. Open the **Results** tab.")

    st.info(
        "**Two tests are scored visually by you** — High-Contrast Spatial Resolution "
        "and Low-Contrast Object Detectability. The ACR manual defines these as visual "
        "(human-judged) tests, so the app shows you the correctly-located images and you "
        "enter what you see below. **They stay at status REVIEW until you score and save — "
        "that's expected, not an error or failure.**"
    )

    st.markdown("### Visual scoring — high-contrast resolution")
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

    lcd_slices = series.spec.lcd_slices
    lcd_range_label = f"{lcd_slices[0]}–{lcd_slices[-1]}"
    st.markdown("### Visual scoring — low-contrast object detectability")
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

# ----- Results ---------------------------------------------------------- #
with tab_results:
    st.subheader("Results")
    if not st.session_state.results:
        st.info("Run the QA tests on the previous tab.")
    else:
        # ---- Overall verdict banner -----
        verdict, counts = _overall_status(st.session_state.results)
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

        # ---- Summary table -----
        rows = []
        for tid, _, _ in TEST_ORDER:
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
        st.dataframe(rows, hide_index=True, use_container_width=True)

        st.markdown("### Per-test details")
        for tid, label, _ in TEST_ORDER:
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
                        hide_index=True, use_container_width=True,
                    )
                if r.annotated_images:
                    img_cols = st.columns(min(2, len(r.annotated_images)))
                    for i, (cap, im) in enumerate(r.annotated_images):
                        with img_cols[i % len(img_cols)]:
                            st.image(im, caption=cap, use_container_width=True)

        st.divider()
        if st.button("Save this run to History"):
            snap = _snapshot_run(series, dict(st.session_state.results))
            st.session_state.history.append(snap)
            st.success(f"Snapshot saved — {len(st.session_state.history)} run(s) in this session.")

# ----- History (in-browser-session) ------------------------------------- #
with tab_history:
    st.subheader("Past QA runs (this browser session)")
    st.caption(
        "History is in-memory and lives only as long as this browser tab. "
        "Use the Export tab to save permanent PDFs."
    )
    if not st.session_state.history:
        st.info("Save a run from the Results tab to populate history.")
    else:
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

# ----- Validation (testing mode) --------------------------------------- #
with tab_validation:
    st.subheader("Validation Mode")
    st.caption(
        "For pilot testing only. Use this tab to record manual measurements alongside "
        "the app's automated results, dataset by dataset. Everything you enter lives "
        "in this browser tab; use **Download log CSV** to save it permanently."
    )

    # ----- Testing checklist -----
    st.markdown("### Per-dataset testing checklist")
    cols = st.columns(2)
    with cols[0]:
        st.markdown(
            "- Upload one anonymized ACR phantom series\n"
            "- Confirm metadata strip matches the scanner/series you expected\n"
            "- Review **Series warnings** (if any)\n"
            "- Confirm Slice Mapping looks right on the visual previews\n"
            "- Run all automated tests"
        )
    with cols[1]:
        st.markdown(
            "- For every test, **open its overlay image** and verify the ROIs land correctly\n"
            "- Note the **Confidence** chip — investigate anything below HIGH\n"
            "- Enter your manual measurements below\n"
            "- Click **Add to validation log**\n"
            "- Export the PDF report and the log CSV"
        )

    st.markdown("### Record this dataset")
    if not st.session_state.results:
        st.info("Run the QA on the Run QA tab first; then come back to record this dataset.")
    else:
        v_cols = st.columns(3)
        ds_name = v_cols[0].text_input(
            "Dataset label",
            value=md.patient_id or md.series_description or "dataset",
            help="A short name you use to identify this dataset in the log.",
        )
        vendor = v_cols[1].selectbox(
            "Vendor",
            options=["Siemens", "GE", "Philips", "Canon", "Other", md.manufacturer or "Unknown"],
            index=5,
        )
        scanner_label = v_cols[2].text_input(
            "Scanner / model",
            value=f"{md.manufacturer} {md.model}".strip(),
        )

        st.markdown(
            "**Manual measurements (optional, leave blank if you don't have one).** "
            "Use whatever your local QA workflow produces — caliper measurements at the "
            "console, your existing tool's numbers, etc. Units shown in parentheses."
        )

        manual: dict[str, str] = {}
        manual_cols = st.columns(3)
        manual_fields = [
            ("geo_slice1",       "Geometric accuracy slice 1 (mm)"),
            ("geo_slice5_h",     "Geometric accuracy slice 5 horizontal (mm)"),
            ("geo_slice5_v",     "Geometric accuracy slice 5 vertical (mm)"),
            ("slice_thickness",  "Slice thickness (mm)"),
            ("slice_position_1", "Slice position Δ slice 1 (mm)"),
            ("slice_position_11","Slice position Δ slice 11 (mm)"),
            ("piu",              "PIU (%)"),
            ("psg",              "PSG (%)"),
            ("res_ul",           "High-contrast UL smallest resolvable (mm)"),
            ("res_lr",           "High-contrast LR smallest resolvable (mm)"),
            ("lcd_total",        "Low-contrast total spokes seen"),
        ]
        for i, (k, label) in enumerate(manual_fields):
            manual[k] = manual_cols[i % 3].text_input(label, value="")

        notes = st.text_area("Notes / observations for this dataset", value="", height=80)

        if st.button("Add to validation log", type="primary"):
            verdict, counts = _overall_status(st.session_state.results)
            row = {
                "logged_at":       datetime.now().isoformat(timespec="seconds"),
                "dataset":         ds_name,
                "vendor":          vendor,
                "scanner":         scanner_label,
                "field_strength_t": md.field_strength_t,
                "study_date":      md.study_date or "",
                "series":          md.series_description or "",
                "sequence":        md.sequence,
                "n_slices":        md.n_slices,
                "verdict":         verdict,
                "pass_count":      counts["PASS"],
                "fail_count":      counts["FAIL"],
                "review_count":    counts["REVIEW"],
                "error_count":     counts["ERROR"],
            }
            # Flatten per-test result + manual side-by-side
            for tid, _, _ in TEST_ORDER:
                r = st.session_state.results.get(tid)
                if r is None:
                    continue
                key = r.measurements[0] if r.measurements else None
                row[f"{tid}__status"]     = r.status_text()
                row[f"{tid}__confidence"] = r.confidence
                row[f"{tid}__warnings"]   = " | ".join(r.warnings)
                if key is not None:
                    row[f"{tid}__app_value"] = key.value
                    row[f"{tid}__unit"]      = key.unit
                if r.error:
                    row[f"{tid}__error"] = r.error
            for k, v in manual.items():
                if v.strip():
                    row[f"manual__{k}"] = v.strip()
            if notes.strip():
                row["notes"] = notes.strip()
            st.session_state.validation_log.append(row)
            st.success(f"Logged. {len(st.session_state.validation_log)} entries this session.")

    st.divider()
    st.markdown("### Validation log this session")
    if not st.session_state.validation_log:
        st.info("No validation entries recorded yet. Use the form above to add one.")
    else:
        # Show a compact view (a few key columns) and a full CSV download
        compact = [
            {
                "Logged":    e["logged_at"],
                "Dataset":   e["dataset"],
                "Vendor":    e["vendor"],
                "Scanner":   e["scanner"],
                "Verdict":   e["verdict"],
                "Pass/Fail/Review/Error": f"{e['pass_count']}/{e['fail_count']}/{e['review_count']}/{e['error_count']}",
            }
            for e in st.session_state.validation_log
        ]
        st.dataframe(compact, hide_index=True, use_container_width=True)

        # Build CSV (union of all keys across entries)
        import csv as _csv
        keys = []
        seen = set()
        for e in st.session_state.validation_log:
            for k in e.keys():
                if k not in seen:
                    seen.add(k); keys.append(k)
        buf = io.StringIO()
        writer = _csv.DictWriter(buf, fieldnames=keys)
        writer.writeheader()
        for e in st.session_state.validation_log:
            writer.writerow(e)
        st.download_button(
            "Download validation log (CSV)",
            buf.getvalue(),
            file_name=f"mriqa_validation_log_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
        if st.button("Clear validation log", help="Wipes the log in this browser tab."):
            st.session_state.validation_log = []
            st.rerun()


# ----- Export ----------------------------------------------------------- #
with tab_export:
    st.subheader("Export QA report")
    if not st.session_state.results:
        st.info("Run the QA tests first.")
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stamp = f"{md.patient_id or 'phantom'}_{md.series_description or 'series'}_{ts}".replace(" ", "_")
        pdf_path = EXPORTS_DIR / f"QAreport_{stamp}.pdf"
        csv_path = EXPORTS_DIR / f"QAreport_{stamp}.csv"
        results_list = [st.session_state.results[t[0]] for t in TEST_ORDER if t[0] in st.session_state.results]

        cgen, _ = st.columns([1, 3])
        if cgen.button("Generate PDF + CSV", type="primary"):
            try:
                write_pdf(pdf_path, series, results_list, app_version=APP_VERSION)
                write_csv(csv_path, series, results_list)
                st.success("Report generated.")
            except Exception as exc:
                st.error(f"Export failed: {exc}")

        if pdf_path.exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download PDF report", f, file_name=pdf_path.name,
                    mime="application/pdf", type="primary",
                )
        if csv_path.exists():
            with open(csv_path, "rb") as f:
                st.download_button(
                    "Download CSV data", f, file_name=csv_path.name, mime="text/csv",
                )
