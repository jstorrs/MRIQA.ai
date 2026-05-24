"""Shared verdict + per-test results renderer.

Used by the Analysis tab (showing the automated subset inline after a
run), the Results tab (full roll-up), the sagittal Analysis tab (which
*is* the only results surface in sagittal mode), and the Manual scoring
tab (just the visual subset, once at least one has been saved).
"""

from __future__ import annotations

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests import AnalysisMode, TestSpec, applicable_test_order, run_test
from ..qa_tests.base import TestResult, verdict_of
from .badges import confidence_badge, status_badge
from .banner import banner
from .history import snapshot_run


# Test IDs that need manual scoring rather than an automated run.
VISUAL_TEST_IDS = {"high_contrast_resolution", "low_contrast_detectability"}

# Session-state keys for cached annotated images on the manual-scoring tab;
# kept in lockstep with results so a results clear sweeps these too.
_VISUAL_IMAGE_CACHE_KEYS = ("_visual_hcr_cache", "_visual_lcd_cache")


def clear_results() -> None:
    """Wipe completed results and any cached visual-test annotations.

    Call from any input handler that invalidates prior numbers (mode flip,
    slice-role override, phantom/field/sequence change). One place owns
    the cache-key list so adding a new visual cache stays a single edit.
    """
    st.session_state.results = {}
    for key in _VISUAL_IMAGE_CACHE_KEYS:
        st.session_state.pop(key, None)


_VERDICT_CSS_CLASS = {
    "PASS": "PASS", "FAIL": "FAIL", "REVIEW": "REVIEW",
    "ERROR": "ERROR", "—": "dash",
}


def run_automated_tests(
    series: DicomSeries, test_order: list[TestSpec], analysis_mode: AnalysisMode,
) -> dict[str, TestResult]:
    """Run every non-visual test in test_order. Returns a dict ready to
    merge into st.session_state.results."""
    out: dict[str, TestResult] = {}
    automated = [
        t for t in applicable_test_order(test_order, analysis_mode, series.metadata.sequence)
        if t.id not in VISUAL_TEST_IDS
    ]
    prog = st.progress(0, text="Running automated tests...")
    for i, t in enumerate(automated):
        prog.progress(
            (i + 1) / max(1, len(automated)),
            text=f"Running {t.label}...",
        )
        out[t.id] = run_test(t, series)
    prog.empty()
    return out


def _pending_visual_nudge(analysis_mode: AnalysisMode, scope: str) -> None:
    """Hint at the next user action when automated tests are in but visual
    scoring is still missing. The nudge is suppressed on the manual tab
    itself (where it would be redundant)."""
    if analysis_mode != "axial" or scope == "manual":
        return
    visual_pending = [
        tid for tid in VISUAL_TEST_IDS if tid not in st.session_state.results
    ]
    if not visual_pending:
        return
    automated_failed = any(
        r.status_text() == "FAIL"
        for tid, r in st.session_state.results.items()
        if tid not in VISUAL_TEST_IDS
    )
    if automated_failed:
        st.warning(
            "One or more automated tests **failed**. Manual scoring is "
            "usually not worth doing until the underlying acquisition / "
            "calibration issue is resolved — but it's available on the "
            "**Manual scoring** tab if you need a complete report."
        )
    else:
        st.info(
            "Automated tests are in. Visual scoring (high-contrast "
            "resolution + low-contrast detectability) is still pending — "
            "open the **Manual scoring** tab to score them when ready."
        )


def render(
    test_order: list[TestSpec],
    analysis_mode: AnalysisMode,
    series: DicomSeries,
    *,
    key_prefix: str,
    scope: str = "all",
) -> None:
    """Render the verdict banner + summary table + per-test details.

    ``scope`` controls which subset of tests appears:

    - ``"automated"`` — non-visual tests only. Used inline on the
      Analysis tab so the user sees what the automated run produced
      without empty REVIEW rows for un-scored visual tests.
    - ``"manual"`` — visual tests only. Used inline on the Manual
      scoring tab so the saved HCR / LCD rows appear right after Save.
    - ``"all"`` — every test. Used on the Results tab and on the
      sagittal Analysis tab.

    The verdict is computed over the displayed subset. The
    save-to-history button only renders for ``scope="all"`` to keep the
    primary "I'm done" action on Results.
    """
    applicable_order = applicable_test_order(test_order, analysis_mode, series.metadata.sequence)
    if scope == "automated":
        displayed_order = [t for t in applicable_order if t.id not in VISUAL_TEST_IDS]
    elif scope == "manual":
        displayed_order = [t for t in applicable_order if t.id in VISUAL_TEST_IDS]
    else:
        displayed_order = applicable_order

    displayed_ids = {t.id for t in displayed_order}
    displayed_results = {
        tid: r for tid, r in st.session_state.results.items()
        if tid in displayed_ids
    }

    _pending_visual_nudge(analysis_mode, scope)
    if analysis_mode == "axial":
        st.caption(
            f"Verdict applies to the selected ACR {series.metadata.sequence} series only; "
            "it is not a combined accreditation determination."
        )

    verdict, counts = verdict_of(displayed_results.values())
    banner(
        f"""
        <div style='font-size:1.05em; font-weight:600;'>
          Overall verdict: {status_badge(verdict)}
        </div>
        <div class='mri-small' style='margin-top:4px;'>
          {counts['PASS']} pass · {counts['FAIL']} fail · {counts['REVIEW']} review · {counts['ERROR']} error
        </div>
        """,
        status=_VERDICT_CSS_CLASS[verdict],
    )

    rows = []
    for t in displayed_order:
        r: TestResult | None = st.session_state.results.get(t.id)
        if r is None:
            rows.append({"Test": t.id, "Status": "—", "Confidence": "—", "Detail": ""})
            continue
        key = r.measurements[0] if r.measurements else None
        if key is None:
            detail = ""
        else:
            value_str = "—" if key.value is None else f"{key.value}"
            detail = f"{key.label}: {value_str} {key.unit}"
            if key.spec:
                detail += f" · spec {key.spec}"
        rows.append({
            "Test": r.test_name,
            "Status": r.status_text(),
            "Confidence": r.confidence_label(),
            "Detail": detail,
            "Error": r.error or "",
        })
    st.dataframe(rows, hide_index=True, width="stretch")

    st.markdown("### Per-test details")
    for t in displayed_order:
        r = st.session_state.results.get(t.id)
        if r is None:
            continue
        title = f"{r.test_name} — {r.status_text()}"
        expanded = r.status_text() in ("FAIL", "ERROR") or r.confidence != "high"
        with st.expander(title, expanded=expanded):
            st.markdown(
                f"{status_badge(r.status_text())} &nbsp; {confidence_badge(r.confidence)}",
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
                    [
                        {
                            "Measurement": m.label, "Value": m.value, "Unit": m.unit,
                            "Spec": m.spec,
                            "Pass": "" if m.passed is None else ("✓" if m.passed else "✗"),
                        }
                        for m in r.measurements
                    ],
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
            snap = snapshot_run(series, dict(st.session_state.results))
            st.session_state.history.append(snap)
            st.success(
                f"Snapshot saved — {len(st.session_state.history)} run(s) in this session."
            )
