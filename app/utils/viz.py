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


def _normalize(image: np.ndarray) -> np.ndarray:
    img = image.astype(np.float32)
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
) -> Image.Image:
    """Render an annotated PIL image. The callback receives the Matplotlib Axes."""
    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
    ax.imshow(_normalize(image), cmap="gray", interpolation="nearest")
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
