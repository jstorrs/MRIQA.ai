"""Validation tab — pilot users record manual measurements alongside the
app's automated results, then download a CSV that pairs them up.

Per-entry fields are appended to ``st.session_state.validation_log`` and
the CSV is emitted on demand by unioning the keys across all entries.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests.base import verdict_of


_AXIAL_MANUAL_FIELDS = [
    ("geo_slice1",       "Geometric accuracy slice 1 (mm)"),
    ("geo_slice5_h",     "Geometric accuracy slice 5 horizontal (mm)"),
    ("geo_slice5_v",     "Geometric accuracy slice 5 vertical (mm)"),
    ("slice_thickness",  "Slice thickness (mm)"),
    ("slice_position_1", "Slice position Δ slice 1 (mm)"),
    ("slice_position_11", "Slice position Δ slice 11 (mm)"),
    ("piu",              "PIU (%)"),
    ("psg",              "PSG (%)"),
    ("res_ul",           "High-contrast UL smallest resolvable (mm)"),
    ("res_lr",           "High-contrast LR smallest resolvable (mm)"),
    ("lcd_total",        "Low-contrast total spokes seen"),
]

_SAGITTAL_MANUAL_FIELDS = [
    ("si_length", "Superior-inferior length (mm)"),
]


def _render_checklist(analysis_mode: str) -> None:
    st.markdown("### Per-dataset testing checklist")
    cols = st.columns(2)
    with cols[0]:
        if analysis_mode == "axial":
            st.markdown(
                "- Upload one anonymized ACR axial phantom series\n"
                "- Confirm metadata strip matches the scanner/series you expected\n"
                "- Review **Series warnings** (if any)\n"
                "- On **Analysis**: confirm slice roles and run the automated tests\n"
                "- Review **Results**; if passing, score the visual tests on **Manual scoring**"
            )
        else:
            st.markdown(
                "- Upload one anonymized ACR sagittal localizer image\n"
                "- Confirm metadata strip matches the scanner/series you expected\n"
                "- Run the S-I length test on **Analysis**"
            )
    with cols[1]:
        st.markdown(
            "- For every test, **open its overlay image** and verify the ROIs land correctly\n"
            "- Note the **Confidence** chip — investigate anything below HIGH\n"
            "- Enter your manual measurements below\n"
            "- Click **Add to validation log**\n"
            "- Export the PDF report and the log CSV"
        )


def _build_log_row(
    *,
    ds_name: str,
    vendor: str,
    scanner_label: str,
    md,
    analysis_mode: str,
    test_order: list,
    manual: dict[str, str],
    notes: str,
) -> dict:
    verdict, counts = verdict_of(st.session_state.results.values())
    row: dict = {
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
        "analysis_mode":   analysis_mode,
    }
    for tid, _, _ in test_order:
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
    return row


def _render_log_download() -> None:
    st.divider()
    st.markdown("### Validation log this session")
    if not st.session_state.validation_log:
        st.info("No validation entries recorded yet. Use the form above to add one.")
        return

    compact = [
        {
            "Logged":    e["logged_at"],
            "Dataset":   e["dataset"],
            "Vendor":    e["vendor"],
            "Scanner":   e["scanner"],
            "Verdict":   e["verdict"],
            "Pass/Fail/Review/Error": (
                f"{e['pass_count']}/{e['fail_count']}/{e['review_count']}/{e['error_count']}"
            ),
        }
        for e in st.session_state.validation_log
    ]
    st.dataframe(compact, hide_index=True, width="stretch")

    keys: list[str] = []
    seen: set[str] = set()
    for e in st.session_state.validation_log:
        for k in e.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys)
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


def render(series: DicomSeries, test_order: list, analysis_mode: str) -> None:
    st.subheader("Validation Mode")
    st.caption(
        "For pilot testing only. Use this tab to record manual measurements "
        "alongside the app's automated results, dataset by dataset. Everything "
        "you enter lives in this browser tab; use **Download log CSV** to save "
        "it permanently."
    )

    md = series.metadata
    _render_checklist(analysis_mode)

    st.markdown("### Record this dataset")
    if not st.session_state.results:
        if analysis_mode == "axial":
            st.info(
                "Run the automated tests on the **Analysis** tab first; "
                "then come back to record this dataset."
            )
        else:
            st.info(
                "Run the S-I length test on the **Analysis** tab first; "
                "then come back to record this dataset."
            )
        _render_log_download()
        return

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
        "Use whatever your local QA workflow produces — caliper measurements at "
        "the console, your existing tool's numbers, etc. Units shown in "
        "parentheses."
    )

    manual_fields = (
        _SAGITTAL_MANUAL_FIELDS if analysis_mode == "sagittal" else _AXIAL_MANUAL_FIELDS
    )
    manual: dict[str, str] = {}
    manual_cols = st.columns(3)
    for i, (k, label) in enumerate(manual_fields):
        manual[k] = manual_cols[i % 3].text_input(label, value="")

    notes = st.text_area("Notes / observations for this dataset", value="", height=80)

    if st.button("Add to validation log", type="primary"):
        row = _build_log_row(
            ds_name=ds_name, vendor=vendor, scanner_label=scanner_label,
            md=md, analysis_mode=analysis_mode, test_order=test_order,
            manual=manual, notes=notes,
        )
        st.session_state.validation_log.append(row)
        st.success(
            f"Logged. {len(st.session_state.validation_log)} entries this session."
        )

    _render_log_download()
