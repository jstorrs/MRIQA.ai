"""Registry of QA tests so the UI and report can iterate them in order.

Two analyses live in this package:

* **Axial series analysis** — the full ACR axial protocol (11 slices), seven
  tests, exposed as ``AXIAL_TEST_ORDER``.
* **Sagittal localizer analysis** — a single-slice sagittal scout, one test
  (S-I length), exposed as ``SAGITTAL_TEST_ORDER``.
"""

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

# Ordered list of (id, label, module). The module must expose a `run(series, ...)` function.
AXIAL_TEST_ORDER = [
    ("geometric_accuracy", "Geometric Accuracy", geometric_accuracy),
    ("high_contrast_resolution", "High-Contrast Spatial Resolution", high_contrast_resolution),
    ("slice_thickness", "Slice Thickness Accuracy", slice_thickness),
    ("slice_position", "Slice Position Accuracy", slice_position),
    ("uniformity", "Image Intensity Uniformity (PIU)", uniformity),
    ("ghosting", "Percent Signal Ghosting (PSG)", ghosting),
    ("low_contrast_detectability", "Low-Contrast Object Detectability", low_contrast_detectability),
]

SAGITTAL_TEST_ORDER = [
    ("localizer_geometric_accuracy", "Geometric Accuracy — Sagittal Localizer", localizer_geometry),
]
