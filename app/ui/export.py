"""Export tab — produces the PDF + CSV deliverables."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests import AnalysisMode, TestSpec, applicable_test_order
from ..qa_tests.base import TestResult
from ..reporting.csv_report import write_csv
from ..reporting.pdf_report import write_pdf


def render(
    series: DicomSeries,
    test_order: list[TestSpec],
    analysis_mode: AnalysisMode,
    exports_dir: Path,
    app_version: str,
) -> None:
    st.subheader("Export QA report")
    if not st.session_state.results:
        st.info("Run the QA tests first.")
        return

    md = series.metadata
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamp = (
        f"{md.patient_id or 'phantom'}_{md.series_description or 'series'}_{ts}"
    ).replace(" ", "_")
    pdf_path = exports_dir / f"QAreport_{stamp}.pdf"
    csv_path = exports_dir / f"QAreport_{stamp}.csv"
    results_list: list[TestResult] = [
        st.session_state.results[t.id]
        for t in applicable_test_order(test_order, analysis_mode, series.metadata.sequence)
        if t.id in st.session_state.results
    ]

    cgen, _ = st.columns([1, 3])
    if cgen.button("Generate PDF + CSV", type="primary"):
        try:
            write_pdf(pdf_path, series, results_list, app_version=app_version)
            write_csv(csv_path, series, results_list)
            st.success("Report generated.")
        except (OSError, ValueError) as exc:
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
