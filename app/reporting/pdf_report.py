"""PDF QA report (ReportLab).

Layout
------
* Cover page: title bar, study + scanner header block, overall verdict box,
  summary table of all tests.
* One page per test: status header, notes, measurements table, annotated
  images (up to two per row).
* Every page has a footer with the engine version, generation timestamp,
  page number, and a short report hash (HMAC) so tampering is detectable.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, PageBreak, Image as RLImage,
)

from ..io_dicom.dicom_loader import DicomSeries
from ..qa_tests.base import TestResult


_STATUS_COLOR = {
    "PASS":   colors.HexColor("#1e8e3e"),
    "FAIL":   colors.HexColor("#d93025"),
    "REVIEW": colors.HexColor("#b06000"),
    "ERROR":  colors.HexColor("#666666"),
    "—":      colors.HexColor("#9aa0a6"),
}
_STATUS_BG = {
    "PASS":   colors.HexColor("#ecf7ee"),
    "FAIL":   colors.HexColor("#fdecea"),
    "REVIEW": colors.HexColor("#fff5e1"),
    "ERROR":  colors.HexColor("#f1f1f1"),
    "—":      colors.HexColor("#f7f9fc"),
}

BRAND = colors.HexColor("#0B7CC4")
INK = colors.HexColor("#1A2330")
GREY = colors.HexColor("#5A6473")
LIGHT_GREY = colors.HexColor("#E3E6EB")


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _pil_to_flowable(pil_img: Image.Image, max_w_in: float = 3.4) -> RLImage:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    w, h = pil_img.size
    aspect = h / w
    width = max_w_in * inch
    return RLImage(buf, width=width, height=width * aspect)


def _overall_verdict(results: Iterable[TestResult]) -> tuple[str, dict]:
    counts = {"PASS": 0, "FAIL": 0, "REVIEW": 0, "ERROR": 0}
    for r in results:
        counts[r.status_text()] = counts.get(r.status_text(), 0) + 1
    if counts["FAIL"]:
        verdict = "FAIL"
    elif counts["ERROR"]:
        verdict = "ERROR"
    elif counts["REVIEW"]:
        verdict = "REVIEW"
    elif counts["PASS"]:
        verdict = "PASS"
    else:
        verdict = "—"
    return verdict, counts


def _signature(payload: dict, secret: str | None = None) -> str:
    """Short HMAC-SHA256 over the canonical JSON payload, hex-truncated."""
    if secret is None:
        secret = os.environ.get("MRIQA_SIGNING_SECRET", "mriqa-default-key")
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    mac = hmac.new(secret.encode(), blob, hashlib.sha256).hexdigest()
    return mac[:16]  # short fingerprint


# --------------------------------------------------------------------------- #
# document template with custom footer                                        #
# --------------------------------------------------------------------------- #


class _ReportDoc(BaseDocTemplate):
    def __init__(self, filename: str, *, footer_meta: dict, **kw):
        kw.setdefault("pagesize", LETTER)
        kw.setdefault("leftMargin", 0.6 * inch)
        kw.setdefault("rightMargin", 0.6 * inch)
        kw.setdefault("topMargin", 0.5 * inch)
        kw.setdefault("bottomMargin", 0.7 * inch)
        super().__init__(filename, **kw)
        self.footer_meta = footer_meta
        frame = Frame(
            self.leftMargin, self.bottomMargin,
            self.width, self.height,
            id="content",
        )
        self.addPageTemplates([PageTemplate(id="default", frames=[frame], onPage=self._draw_footer)])

    def _draw_footer(self, canvas, doc):
        canvas.saveState()
        fm = self.footer_meta
        # divider
        canvas.setStrokeColor(LIGHT_GREY)
        canvas.setLineWidth(0.4)
        y = 0.55 * inch
        canvas.line(0.6 * inch, y, doc.pagesize[0] - 0.6 * inch, y)
        # footer text
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        left = f"MRIQA.ai · engine v{fm.get('version')} · {fm.get('generated_at')}"
        right = f"sig {fm.get('signature')} · page {doc.page}"
        canvas.drawString(0.6 * inch, 0.36 * inch, left)
        canvas.drawRightString(doc.pagesize[0] - 0.6 * inch, 0.36 * inch, right)
        canvas.setFillColor(GREY)
        canvas.setFont("Helvetica-Oblique", 7)
        canvas.drawString(
            0.6 * inch, 0.22 * inch,
            "Decision-support output. Not a medical device. Not for diagnostic use.",
        )
        canvas.restoreState()


# --------------------------------------------------------------------------- #
# Cover blocks                                                                #
# --------------------------------------------------------------------------- #


def _header_band(spec_name: str) -> Table:
    """The thin brand band at the top of the cover."""
    band = Table([[Paragraph(
        f"<para align='left'><font color='white' size='14'><b>MRIQA.ai</b></font>"
        f"&nbsp;&nbsp;&nbsp;<font color='white' size='10'>{spec_name} QA report</font></para>",
        ParagraphStyle("brand", textColor=colors.white),
    )]], colWidths=[7.3 * inch])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return band


def _meta_block(series: DicomSeries) -> Table:
    md = series.metadata
    data = [
        ["Site / Org",        "—",                                "Manufacturer", md.manufacturer or "—"],
        ["Scanner",           md.model or "—",                    "Field",        f"{md.field_strength_t:.1f} T"],
        ["Phantom",           series.spec.name,                   "Sequence",     md.sequence],
        ["Patient / Phantom", md.patient_name or "—",             "Study date",   md.study_date or "—"],
        ["Patient ID",        md.patient_id or "—",               "Series",       f"{md.series_description} (#{md.series_number})"],
        ["Pixel spacing",     f"{md.pixel_spacing_mm[0]:.3f} × {md.pixel_spacing_mm[1]:.3f} mm",
         "Slice thickness",   f"{md.slice_thickness_mm:.2f} mm"],
        ["Slices",            str(md.n_slices),                   "TR / TE",      f"{md.repetition_time_ms:.0f} / {md.echo_time_ms:.1f} ms"],
    ]
    tbl = Table(data, colWidths=[1.2 * inch, 2.4 * inch, 1.1 * inch, 2.6 * inch])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F7FA")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F5F7FA")),
        ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, LIGHT_GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tbl


def _verdict_box(verdict: str, counts: dict) -> Table:
    bg = _STATUS_BG.get(verdict, _STATUS_BG["—"])
    fg = _STATUS_COLOR.get(verdict, _STATUS_COLOR["—"])
    summary = (
        f"<font color='{INK.hexval()}' size='10'>"
        f"Pass <b>{counts['PASS']}</b> · "
        f"Fail <b>{counts['FAIL']}</b> · "
        f"Review <b>{counts['REVIEW']}</b> · "
        f"Error <b>{counts['ERROR']}</b>"
        f"</font>"
    )
    paragraph = Paragraph(
        f"<para align='left'>"
        f"<font size='9' color='{GREY.hexval()}'>OVERALL VERDICT</font><br/>"
        f"<font size='22' color='{fg.hexval()}'><b>{verdict}</b></font><br/>"
        f"{summary}"
        f"</para>",
        ParagraphStyle("v", leading=18),
    )
    tbl = Table([[paragraph]], colWidths=[7.3 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
    ]))
    return tbl


def _summary_table(results: list[TestResult]) -> Table:
    rows = [["#", "Test", "Status", "Conf.", "Key measurement"]]
    for i, r in enumerate(results, 1):
        key = ""
        if r.measurements:
            m = r.measurements[0]
            key = f"{m.label}: {m.value} {m.unit}".strip()
            if m.spec:
                key += f"   (spec {m.spec})"
        conf = getattr(r, "confidence_label", lambda: "HIGH")()
        rows.append([str(i), r.test_name, r.status_text(), conf, key])
    tbl = Table(rows, colWidths=[0.35 * inch, 2.5 * inch, 0.8 * inch, 0.8 * inch, 2.9 * inch])
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF3F8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, LIGHT_GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    conf_color = {"HIGH": _STATUS_COLOR["PASS"], "MEDIUM": _STATUS_COLOR["REVIEW"], "LOW": _STATUS_COLOR["FAIL"]}
    for i, r in enumerate(results, 1):
        c = _STATUS_COLOR.get(r.status_text(), colors.black)
        style.append(("TEXTCOLOR", (2, i), (2, i), c))
        style.append(("FONT", (2, i), (2, i), "Helvetica-Bold", 9))
        conf_label = getattr(r, "confidence_label", lambda: "HIGH")()
        cc = conf_color.get(conf_label, INK)
        style.append(("TEXTCOLOR", (3, i), (3, i), cc))
        style.append(("FONT", (3, i), (3, i), "Helvetica-Bold", 9))
    tbl.setStyle(TableStyle(style))
    return tbl


def _measurements_table(r: TestResult) -> Table:
    rows = [["Measurement", "Value", "Unit", "Spec", "Pass"]]
    for m in r.measurements:
        passed = "" if m.passed is None else ("✓" if m.passed else "✗")
        rows.append([m.label, f"{m.value}", m.unit, m.spec, passed])
    tbl = Table(rows, colWidths=[2.6 * inch, 1.0 * inch, 0.7 * inch, 2.0 * inch, 0.5 * inch])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF3F8")),
        ("BOX", (0, 0), (-1, -1), 0.5, LIGHT_GREY),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, LIGHT_GREY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (4, -1), "CENTER"),
    ]))
    return tbl


# --------------------------------------------------------------------------- #
# Main entry                                                                  #
# --------------------------------------------------------------------------- #


def write_pdf(
    path: str | Path,
    series: DicomSeries,
    results: list[TestResult],
    *,
    app_version: str = "0.0.0",
) -> Path:
    path = Path(path)
    verdict, counts = _overall_verdict(results)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Tamper-evident signature
    sig_payload = {
        "version": app_version,
        "generated_at": generated_at,
        "verdict": verdict,
        "counts": counts,
        "measurements": [
            {
                "test_id": r.test_id,
                "status": r.status_text(),
                "values": [(m.label, m.value, m.unit) for m in r.measurements],
            }
            for r in results
        ],
    }
    signature = _signature(sig_payload)

    doc = _ReportDoc(
        str(path),
        footer_meta={
            "version": app_version,
            "generated_at": generated_at,
            "signature": signature,
        },
        title=f"{series.spec.name} QA Report",
    )

    styles = getSampleStyleSheet()
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=INK, fontSize=13, spaceAfter=4)
    body = ParagraphStyle("body", parent=styles["BodyText"], textColor=INK, fontSize=9, leading=12)
    caption = ParagraphStyle("cap", parent=body, textColor=GREY, fontSize=8, leading=10)

    story = []

    # ----- Cover -----
    story.append(_header_band(series.spec.name))
    story.append(Spacer(1, 10))
    story.append(_meta_block(series))
    story.append(Spacer(1, 12))
    story.append(_verdict_box(verdict, counts))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Summary of all tests", h2))
    story.append(_summary_table(results))
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "This is a decision-support report generated by MRIQA.ai. Threshold "
        "values are taken from the ACR Large and Medium Phantom Test Guidance "
        "(Oct 2022). Final QA approval and clinical use of the scanner remain "
        "the responsibility of the supervising medical physicist.", caption,
    ))
    story.append(PageBreak())

    # ----- Per-test pages -----
    for r in results:
        status = r.status_text()
        c = _STATUS_COLOR.get(status, INK)
        story.append(Paragraph(
            f"<font color='{c.hexval()}'><b>{r.test_name}</b></font>"
            f" &nbsp;<font size='10' color='{GREY.hexval()}'>— {status}</font>"
            f" &nbsp;<font size='9' color='{GREY.hexval()}'>"
            f"(confidence: {getattr(r, 'confidence_label', lambda: 'HIGH')()})</font>",
            ParagraphStyle("h", parent=h2, fontSize=14, leading=18),
        ))
        # Warnings, if any
        warnings = getattr(r, "warnings", None) or []
        if warnings:
            warning_html = "<br/>".join(f"• {w}" for w in warnings)
            story.append(Paragraph(
                f"<font color='{_STATUS_COLOR['REVIEW'].hexval()}'><b>Detection warnings:</b></font><br/>{warning_html}",
                body,
            ))
            story.append(Spacer(1, 6))
        if r.notes:
            story.append(Paragraph(r.notes, body))
            story.append(Spacer(1, 6))
        if r.error:
            story.append(Paragraph(
                f"<font color='{_STATUS_COLOR['ERROR'].hexval()}'>Error: {r.error}</font>",
                body,
            ))
            story.append(Spacer(1, 6))
        if r.measurements:
            story.append(_measurements_table(r))
            story.append(Spacer(1, 10))
        # Annotated images side-by-side, up to 2 per row
        flow = []
        for cap, img in r.annotated_images:
            flow.append((cap, _pil_to_flowable(img, max_w_in=3.3)))
        for i in range(0, len(flow), 2):
            pair = flow[i:i + 2]
            row = [item[1] for item in pair]
            caps = [Paragraph(item[0], caption) for item in pair]
            t1 = Table([row, caps], colWidths=[3.4 * inch] * len(pair))
            t1.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(t1)
            story.append(Spacer(1, 6))
        story.append(PageBreak())

    doc.build(story)
    return path
