"""Matplotlib helpers to render annotated QA images.

Every QA test should call `render_annotated()` with its own draw callback
so the look-and-feel stays consistent across the report.
"""

from __future__ import annotations

import io
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def normalize(image: np.ndarray, wl: float | None = None, ww: float | None = None) -> np.ndarray:
    """Map an MR image to [0, 1] floats for display.

    With ``wl``/``ww`` (window level / width), applies a fixed DICOM-style
    window. Otherwise falls back to a 2-98 percentile auto-window. Returns
    a zero-array for empty or fully-non-finite input so callers don't have
    to guard the upstream.
    """
    img = image.astype(np.float32)
    if img.size == 0 or not np.isfinite(img).any():
        return np.zeros_like(img) if img.size else np.zeros((1, 1), dtype=np.float32)
    if wl is not None and ww is not None and ww > 0:
        lo, hi = wl - ww / 2.0, wl + ww / 2.0
        return np.clip((img - lo) / (hi - lo + 1e-9), 0.0, 1.0)
    p2, p98 = np.percentile(img, (2, 98))
    if p98 - p2 < 1e-6:
        p2, p98 = float(img.min()), float(img.max() + 1)
    return np.clip((img - p2) / (p98 - p2), 0.0, 1.0)


def render_annotated(
    image: np.ndarray,
    title: str,
    draw_fn: Callable[[plt.Axes], None],
    figsize: tuple[float, float] = (5.5, 5.5),
    dpi: int = 130,
    wl: float | None = None,
    ww: float | None = None,
) -> Image.Image:
    """Render an annotated PIL image. The callback receives the Matplotlib Axes.

    Optional `wl`/`ww` apply an explicit window level/width instead of the
    default 2–98 percentile auto-window (useful for faint low-contrast detail).
    """
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.imshow(normalize(image, wl, ww), cmap="gray", interpolation="nearest")
    ax.set_title(title, fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    draw_fn(ax)
    fig.tight_layout(pad=0.2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")
