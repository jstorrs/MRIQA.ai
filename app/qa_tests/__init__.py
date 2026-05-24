"""Registry of QA tests so the UI and report can iterate them in order.

Two analyses live in this package:

* **Axial series analysis** — the full ACR axial protocol (11 slices), seven
  tests, exposed as ``AXIAL_TEST_ORDER``.
* **Sagittal localizer analysis** — a single-slice sagittal scout, one test
  (S-I length), exposed as ``SAGITTAL_TEST_ORDER``.

The entry to a single test is a ``TestSpec`` — a frozen dataclass bundling
the test id, human label, and the module exposing ``run(series, ...)``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Literal

from .base import TestResult as TestResult  # re-export
from . import (
    geometric_accuracy,
    high_contrast_resolution,
    slice_thickness,
    slice_position,
    uniformity,
    ghosting,
    low_contrast_detectability,
    localizer_geometry,
)

if TYPE_CHECKING:
    from ..io_dicom.dicom_loader import DicomSeries

logger = logging.getLogger(__name__)


# Two modes today — axial protocol and sagittal localizer. A Literal is
# enough; promote to an enum if more modes appear.
AnalysisMode = Literal["axial", "sagittal"]


@dataclass(frozen=True)
class TestSpec:
    """One QA test in the registry — id, label, and the module exposing ``run``."""

    id: str
    label: str
    runner: ModuleType
    axial_sequences: frozenset[str] | None = None


AXIAL_TEST_ORDER: list[TestSpec] = [
    TestSpec("geometric_accuracy", "Geometric Accuracy", geometric_accuracy, frozenset({"T1"})),
    TestSpec("high_contrast_resolution", "High-Contrast Spatial Resolution", high_contrast_resolution, frozenset({"T1", "T2"})),
    TestSpec("slice_thickness", "Slice Thickness Accuracy", slice_thickness, frozenset({"T1", "T2"})),
    TestSpec("slice_position", "Slice Position Accuracy", slice_position, frozenset({"T1", "T2"})),
    TestSpec("uniformity", "Image Intensity Uniformity (PIU)", uniformity, frozenset({"T1", "T2"})),
    TestSpec("ghosting", "Percent Signal Ghosting (PSG)", ghosting, frozenset({"T1"})),
    TestSpec("low_contrast_detectability", "Low-Contrast Object Detectability", low_contrast_detectability, frozenset({"T1", "T2"})),
]

SAGITTAL_TEST_ORDER: list[TestSpec] = [
    TestSpec("localizer_geometric_accuracy", "Geometric Accuracy — Sagittal Localizer", localizer_geometry),
]


def run_test(test: TestSpec, series: "DicomSeries") -> TestResult:
    """Run a single QA test and guarantee a TestResult is returned.

    Each test's body wraps itself in ``TestResult.capture_failures`` so an
    exception inside the detector becomes ``error=...`` on the result. This
    wrapper is the belt-and-suspenders for the rare case the test raises
    *before* entering that context manager (e.g. failing to construct the
    TestResult itself), so the run loop is never crashed by one bad test.
    """
    try:
        return test.runner.run(series, spec=series.spec)
    except Exception as exc:  # noqa: BLE001 — surface to user, never crash run loop
        logger.exception("QA test %r crashed outside capture_failures", test.id)
        return TestResult(
            test_id=test.id, test_name=test.label, automated=True,
            passed=None, error=f"{type(exc).__name__}: {exc}",
        )


def applicable_test_order(
    test_order: list[TestSpec],
    analysis_mode: AnalysisMode,
    sequence: str,
) -> list[TestSpec]:
    """Return tests applicable to the selected single-series analysis."""
    if analysis_mode != "axial":
        return list(test_order)
    return [
        test for test in test_order
        if test.axial_sequences is None or sequence in test.axial_sequences
    ]
