"""Single source of truth for status and confidence colors.

The Streamlit UI and the PDF report both consume these values. Streamlit
uses the hex strings directly; the PDF wraps them in
``reportlab.lib.colors.HexColor`` at import time.
"""

from __future__ import annotations


# Pass / fail / review / error swatches used in chips, badges and table cells.
STATUS_COLORS: dict[str, str] = {
    "PASS":   "#1e8e3e",
    "FAIL":   "#d93025",
    "REVIEW": "#b06000",
    "ERROR":  "#666666",
    "—":      "#9aa0a6",
}

STATUS_BG: dict[str, str] = {
    "PASS":   "#ecf7ee",
    "FAIL":   "#fdecea",
    "REVIEW": "#fff5e1",
    "ERROR":  "#f1f1f1",
    "—":      "#f7f9fc",
}

# HIGH/MEDIUM/LOW labels reuse the pass/review/fail swatches so the
# confidence chip and the status chip read the same.
CONFIDENCE_COLORS: dict[str, str] = {
    "HIGH":   STATUS_COLORS["PASS"],
    "MEDIUM": STATUS_COLORS["REVIEW"],
    "LOW":    STATUS_COLORS["FAIL"],
}

# Layout-level chrome.
BRAND = "#0B7CC4"
INK = "#1A2330"
GREY = "#5A6473"
LIGHT_GREY = "#E3E6EB"
