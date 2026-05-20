"""Registry of QA tests so the UI and report can iterate them in order."""

from .base import TestResult  # re-export
from . import (
    geometric_accuracy,
    high_contrast_resolution,
    slice_thickness,
    slice_position,
    uniformity,
    ghosting,
    low_contrast_detectability,
)

# Ordered list of (id, label, module). The module must expose a `run(series, ...)` function.
TEST_ORDER = [
    ("geometric_accuracy", "Geometric Accuracy", geometric_accuracy),
    ("high_contrast_resolution", "High-Contrast Spatial Resolution", high_contrast_resolution),
    ("slice_thickness", "Slice Thickness Accuracy", slice_thickness),
    ("slice_position", "Slice Position Accuracy", slice_position),
    ("uniformity", "Image Intensity Uniformity (PIU)", uniformity),
    ("ghosting", "Percent Signal Ghosting (PSG)", ghosting),
    ("low_contrast_detectability", "Low-Contrast Object Detectability", low_contrast_detectability),
]
