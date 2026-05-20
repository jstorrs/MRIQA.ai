"""Flat CSV export of a QA run."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests.base import TestResult


def write_csv(path: str | Path, series: DicomSeries, results: Iterable[TestResult]) -> Path:
    path = Path(path)
    md = series.metadata
    rows = []
    for r in results:
        for m in r.measurements:
            rows.append({
                "test_id": r.test_id,
                "test_name": r.test_name,
                "measurement": m.label,
                "value": m.value,
                "unit": m.unit,
                "spec": m.spec,
                "measurement_pass": m.passed,
                "test_status": r.status_text(),
                "test_passed_overall": r.passed,
                "patient_name": md.patient_name,
                "patient_id": md.patient_id,
                "study_date": md.study_date,
                "manufacturer": md.manufacturer,
                "model": md.model,
                "field_strength_t": md.field_strength_t,
                "series_description": md.series_description,
                "sequence": md.sequence,
                "pixel_spacing_row_mm": md.pixel_spacing_mm[0],
                "pixel_spacing_col_mm": md.pixel_spacing_mm[1],
                "slice_thickness_mm": md.slice_thickness_mm,
                "n_slices": md.n_slices,
            })
    if not rows:
        rows.append({"test_id": "(no measurements)"})
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path
