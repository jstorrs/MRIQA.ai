"""Streamlit-renderable HTML chips for status and confidence."""

from __future__ import annotations

import numpy as np

from ..utils import theme, viz


_CONFIDENCE_LABELS = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}


def status_badge(status: str) -> str:
    """Return a markdown-friendly colored badge for a test status."""
    color = theme.STATUS_COLORS.get(status, "#cccccc")
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:0.78em;font-weight:600;letter-spacing:0.5px;'>"
        f"{status}</span>"
    )


def confidence_badge(conf: str) -> str:
    """Return a markdown-friendly colored badge for detection confidence."""
    label = _CONFIDENCE_LABELS.get(conf, "—")
    color = theme.CONFIDENCE_COLORS.get(label, "#cccccc")
    return (
        f"<span style='background:white;color:{color};border:1px solid {color};"
        f"padding:1px 8px;border-radius:10px;font-size:0.74em;font-weight:600;"
        f"letter-spacing:0.5px;'>confidence: {label}</span>"
    )


def normalize_img(
    img: np.ndarray, wl: float | None = None, ww: float | None = None,
) -> np.ndarray:
    """uint8 view of an MR image for ``st.image``. Delegates the actual
    windowing to ``viz.normalize`` so the Streamlit display and the PDF
    overlays agree pixel-for-pixel."""
    return (viz.normalize(img, wl=wl, ww=ww) * 255).astype(np.uint8)
