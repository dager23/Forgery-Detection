"""PDF verification report (ReportLab)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from docauth import __version__

VERDICT_COLORS = {
    "authentic": colors.HexColor("#15803d"),
    "suspicious": colors.HexColor("#b45309"),
    "tampered": colors.HexColor("#b91c1c"),
}
VERDICT_LABEL = {"authentic": "ACCEPTED", "suspicious": "SUSPICIOUS", "tampered": "REJECTED"}
BOX_COLORS = [(40, 40, 230), (0, 140, 255), (200, 60, 200), (0, 170, 90), (230, 120, 0)]


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _annotated_page(adir: Path, page: dict, modules: list[dict]) -> np.ndarray | None:
    img = cv2.imread(str(adir / page["image"]))
    if img is None:
        return None
    sx = img.shape[1] / page["width"]
    sy = img.shape[0] / page["height"]
    t = max(2, img.shape[1] // 300)
    for mi, m in enumerate(m for m in modules if m["status"] == "ok"):
        col = BOX_COLORS[mi % len(BOX_COLORS)]
        for b in m["boxes"]:
            if b["page"] != page["index"]:
                continue
            p1 = (int(b["x"] * sx), int(b["y"] * sy))
            p2 = (int((b["x"] + b["w"]) * sx), int((b["y"] + b["h"]) * sy))
            cv2.rectangle(img, p1, p2, col, t)
    return img


def _rl_image(img: np.ndarray, max_w: float, max_h: float) -> Image:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h)
    return Image(io.BytesIO(buf.tobytes()), width=w * scale, height=h * scale)


def build_report(analysis: dict[str, Any], adir: Path) -> bytes:
    """``analysis`` is the AnalysisOut dict (with ``result``); ``adir`` holds its artifacts."""
    result = analysis["result"] or {}
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"DocAuth report - {analysis['filename']}",
        author="DocAuth",
    )
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, alignment=TA_LEFT, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10, textColor=colors.grey)
    cell = ParagraphStyle("c", parent=body, fontSize=8.5, leading=11)

    verdict = analysis.get("verdict") or "suspicious"
    vcol = VERDICT_COLORS.get(verdict, colors.grey)
    story: list = [Paragraph("DocAuth verification report", h1)]
    created = analysis["created_at"]
    if isinstance(created, datetime):
        created = created.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    meta = [
        ["File", _esc(analysis["filename"])],
        ["SHA-256", analysis["sha256"]],
        ["Analysis ID", analysis["id"]],
        ["Submitted", f"{created} by {_esc(analysis.get('owner_name') or '-')}"],
        [
            "Template",
            _esc(
                analysis.get("template_name")
                or (result.get("template") or {}).get("name")
                or "none"
            ),
        ],
        ["Pages", f"{result.get('document', {}).get('analysed_pages', '-')} analysed"],
    ]
    t = Table(
        [[Paragraph(f"<b>{k}</b>", cell), Paragraph(str(v), cell)] for k, v in meta],
        colWidths=[30 * mm, 148 * mm],
    )
    t.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])
    )
    story += [t, Spacer(1, 8)]

    label = VERDICT_LABEL.get(verdict, verdict)
    score = analysis.get("score") or 0
    banner = Table(
        [
            [
                Paragraph(f"<font color='white' size='16'><b>{label}</b></font>", body),
                Paragraph(
                    f"<font color='white' size='13'>Authenticity score <b>{score:.0f}</b> / 100"
                    "</font>",
                    body,
                ),
            ]
        ],
        colWidths=[70 * mm, 108 * mm],
        rowHeights=[16 * mm],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), vcol),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    story += [banner, Spacer(1, 6), Paragraph(_esc(result.get("summary", "")), body)]

    story.append(Paragraph("Module results", h2))
    rows = [
        [Paragraph(f"<b>{h}</b>", cell) for h in ("Module", "Score /10", "Confidence", "Finding")]
    ]
    for m in result.get("modules", []):
        score = "-" if m["status"] != "ok" else f"{m['score10']:.1f}"
        conf = "-" if m["status"] != "ok" else f"{m['confidence'] * 100:.0f}%"
        rows.append(
            [
                Paragraph(_esc(m["title"]), cell),
                Paragraph(score, cell),
                Paragraph(conf, cell),
                Paragraph(_esc(m["summary"]), cell),
            ]
        )
    mt = Table(rows, colWidths=[42 * mm, 18 * mm, 20 * mm, 98 * mm], repeatRows=1)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, m in enumerate(result.get("modules", []), start=1):
        if m["status"] == "ok":
            s10 = m["score10"]
            c = "#dcfce7" if s10 >= 8 else ("#fef3c7" if s10 >= 4 else "#fee2e2")
            style.append(("BACKGROUND", (1, i), (1, i), colors.HexColor(c)))
    mt.setStyle(TableStyle(style))
    story.append(mt)

    findings = [
        (m["title"], f)
        for m in result.get("modules", [])
        for f in m["findings"]
        if f["severity"] in ("medium", "high")
    ]
    if findings:
        story.append(Paragraph("Key findings", h2))
        for title, f in findings[:25]:
            sev = "#b91c1c" if f["severity"] == "high" else "#b45309"
            story.append(
                Paragraph(
                    f"<font color='{sev}'><b>{f['severity'].upper()}</b></font> "
                    f"<b>{_esc(title)}:</b> {_esc(f['message'])}",
                    body,
                )
            )

    adir = Path(adir)
    pages = result.get("pages", [])
    for page in pages[:3]:
        img = _annotated_page(adir, page, result.get("modules", []))
        if img is None:
            continue
        story += [
            PageBreak(),
            Paragraph(f"Page {page['index'] + 1} - flagged regions", h2),
            _rl_image(img, 178 * mm, 230 * mm),
        ]

    thumbs = []
    for m in result.get("modules", []):
        for a in m.get("artifacts", []):
            if a["page"] == 0 and a["kind"] == "image":
                p = adir / a["file"]
                img = cv2.imread(str(p))
                if img is not None:
                    thumbs.append(
                        [Paragraph(_esc(a["label"]), cell), _rl_image(img, 85 * mm, 110 * mm)]
                    )
    if thumbs:
        story += [PageBreak(), Paragraph("Forensic visualisations", h2)]
        grid = [
            thumbs[i : i + 2] + [""] * (2 - len(thumbs[i : i + 2]))
            for i in range(0, len(thumbs), 2)
        ]
        story.append(Table(grid, colWidths=[89 * mm, 89 * mm]))

    story += [
        Spacer(1, 12),
        Paragraph(
            "This report lists automated forensic indicators. It is not a legal determination; "
            "confirm critical decisions with the issuing authority.",
            small,
        ),
    ]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(16 * mm, 10 * mm, f"DocAuth v{__version__} - {analysis['id']}")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
