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

from dataclasses import dataclass
from types import ModuleType
from typing import Literal

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


# Two modes today — axial protocol and sagittal localizer. A Literal is
# enough; promote to an enum if more modes appear.
AnalysisMode = Literal["axial", "sagittal"]


@dataclass(frozen=True)
class TestSpec:
    """One QA test in the registry — id, label, and the module exposing ``run``."""

    id: str
    label: str
    runner: ModuleType


AXIAL_TEST_ORDER: list[TestSpec] = [
    TestSpec("geometric_accuracy", "Geometric Accuracy", geometric_accuracy),
    TestSpec("high_contrast_resolution", "High-Contrast Spatial Resolution", high_contrast_resolution),
    TestSpec("slice_thickness", "Slice Thickness Accuracy", slice_thickness),
    TestSpec("slice_position", "Slice Position Accuracy", slice_position),
    TestSpec("uniformity", "Image Intensity Uniformity (PIU)", uniformity),
    TestSpec("ghosting", "Percent Signal Ghosting (PSG)", ghosting),
    TestSpec("low_contrast_detectability", "Low-Contrast Object Detectability", low_contrast_detectability),
]

SAGITTAL_TEST_ORDER: list[TestSpec] = [
    TestSpec("localizer_geometric_accuracy", "Geometric Accuracy — Sagittal Localizer", localizer_geometry),
]
