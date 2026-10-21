"""Metadata analysis (README module 1).

Images: EXIF software tags, capture-vs-modify timestamps, ISO / camera fields, XMP edit history,
Photoshop resource blocks, EXIF-thumbnail mismatch and JPEG quality.
PDFs: producer/creator tools, creation-vs-modification dates, incremental revisions, whiteout
boxes, visible text over scans, mixed fonts inside a line, annotations and scripts.
"""

from __future__ import annotations

import contextlib
import io
import re
from datetime import datetime

import cv2
import numpy as np
from PIL import Image

from docauth.forensics.modules.base import Module
from docauth.forensics.types import Box, Document, Finding, ModuleResult, suspicion_from_findings

IMAGE_EDITORS = [
    "photoshop",
    "gimp",
    "paint.net",
    "pixlr",
    "canva",
    "snapseed",
    "picsart",
    "affinity",
    "pixelmator",
    "illustrator",
    "inkscape",
    "fotor",
    "photopea",
    "facetune",
    "meitu",
    "polarr",
    "luminar",
    "paintshop",
    "corel",
    "acdsee",
    "krita",
    "photoscape",
    "befunky",
    "remini",
]
MILD_EDITORS = ["lightroom", "capture one", "darktable", "rawtherapee", "photos", "preview"]
SCAN_TOOLS = ["camscanner", "adobe scan", "microsoft lens", "office lens", "genius scan"]
PDF_EDITORS = [
    "pdfescape",
    "sejda",
    "ilovepdf",
    "smallpdf",
    "pdf-xchange",
    "phantompdf",
    "foxit pdf editor",
    "nitro",
    "pdfelement",
    "wondershare",
    "pdf candy",
    "soda pdf",
    "pdffiller",
    "dochub",
    "pdf24",
    "canva",
    "photoshop",
    "illustrator",
    "inkscape",
    "pdf editor",
    "abcdpdf",
    "pdfgear",
    "xodo",
]
SYMBOL_FONTS = ("symbol", "wingding", "zapf", "dingbat", "webdings", "marlett")

# Standard IJG luminance quantisation table (quality 50), zig-zag order irrelevant for ratios
_IJG_LUMA = np.array(
    [
        16,
        11,
        10,
        16,
        24,
        40,
        51,
        61,
        12,
        12,
        14,
        19,
        26,
        58,
        60,
        55,
        14,
        13,
        16,
        24,
        40,
        57,
        69,
        56,
        14,
        17,
        22,
        29,
        51,
        87,
        80,
        62,
        18,
        22,
        37,
        56,
        68,
        109,
        103,
        77,
        24,
        35,
        55,
        64,
        81,
        104,
        113,
        92,
        49,
        64,
        78,
        87,
        103,
        121,
        120,
        101,
        72,
        92,
        95,
        98,
        112,
        100,
        103,
        99,
    ],
    dtype=np.float64,
)


class MetadataModule(Module):
    key = "metadata"
    title = "Metadata analysis"
    description = "Camera/EXIF and PDF metadata: editing software, timestamps, revisions."

    def run(self, doc: Document, ctx) -> ModuleResult:
        res = self.result()
        if doc.kind == "pdf":
            _analyse_pdf(doc, res)
        else:
            _analyse_image(doc, res)
        res.suspicion = suspicion_from_findings(res.findings)
        bad = [f for f in res.findings if f.severity in ("medium", "high")]
        if bad:
            res.summary = bad[0].message
        elif res.confidence < 0.5:
            res.summary = "Little metadata present; nothing conclusive either way."
        else:
            res.summary = "Metadata is consistent with an unedited original."
        return res


# --------------------------------------------------------------------------------------------
# Images


def _analyse_image(doc: Document, res: ModuleResult) -> None:
    import exifread

    fields: dict[str, str] = {}
    try:
        tags = exifread.process_file(io.BytesIO(doc.data), details=False, debug=False)
    except Exception:  # noqa: BLE001 - exifread can choke on odd files
        tags = {}
    thumb = tags.pop("JPEGThumbnail", None)
    tags.pop("TIFFThumbnail", None)
    for k, v in tags.items():
        s = str(v).strip()
        if s and len(s) < 200:
            fields[k] = s

    try:
        pil = Image.open(io.BytesIO(doc.data))
        info = dict(pil.info)
    except Exception:  # noqa: BLE001
        pil, info = None, {}
    for k in ("Software", "software", "Author", "Description", "Creation Time", "Comment"):
        if isinstance(info.get(k), str) and info[k].strip():
            fields[f"PNG {k}"] = info[k].strip()[:200]

    xmp = _extract_xmp(doc.data)
    if xmp:
        for tag in ("CreatorTool", "CreateDate", "ModifyDate", "MetadataDate"):
            m = re.search(rf'(?:xmp:)?{tag}(?:="|>)([^"<]+)', xmp)
            if m:
                fields[f"XMP {tag}"] = m.group(1)[:200]

    res.metrics["fields"] = dict(sorted(fields.items())[:60])
    has_exif = any(k.startswith(("EXIF", "Image")) for k in fields)
    res.confidence = 0.9 if (has_exif or xmp) else 0.35

    # 1. Editing software
    software_text = " | ".join(
        fields.get(k, "")
        for k in ("Image Software", "XMP CreatorTool", "PNG Software", "PNG software")
    ).lower()
    agents = re.findall(r'softwareAgent="([^"]+)"', xmp or "")
    software_text += " | " + " | ".join(a.lower() for a in agents)
    editor = next((e for e in IMAGE_EDITORS if e in software_text), None)
    mild = next((e for e in MILD_EDITORS if re.search(rf"\b{re.escape(e)}\b", software_text)), None)
    scan = next((e for e in SCAN_TOOLS if e in software_text), None)
    if editor:
        res.findings.append(
            Finding("high", f"Image was saved by editing software ({editor.title()}).")
        )
    elif mild:
        res.findings.append(Finding("low", f"Image was processed in {mild.title()}."))
    elif scan:
        res.findings.append(Finding("info", f"Captured with a scanning app ({scan.title()})."))

    # 2. XMP edit history / Photoshop resources
    if xmp and re.search(r'stEvt:action="(saved|converted|derived|edited)"', xmp):
        n = len(re.findall(r'stEvt:action="saved"', xmp))
        res.findings.append(
            Finding("medium", f"XMP edit history records {max(n, 1)} save operation(s).")
        )
    if b"Photoshop 3.0\x008BIM" in doc.data[:200000] and not editor:
        res.findings.append(Finding("medium", "Contains Adobe Photoshop resource blocks."))

    # 3. Capture vs modification time (README: creation vs modified date)
    original = _parse_exif_dt(fields.get("EXIF DateTimeOriginal"))
    modified = _parse_exif_dt(fields.get("Image DateTime"))
    if original and modified:
        delta = abs((modified - original).total_seconds())
        if delta > 60:
            res.findings.append(
                Finding(
                    "medium",
                    f"Modified {_human_delta(delta)} after it was captured "
                    f"({original:%Y-%m-%d %H:%M} -> {modified:%Y-%m-%d %H:%M}).",
                )
            )
    xc, xm = (
        _parse_xmp_dt(fields.get("XMP CreateDate")),
        _parse_xmp_dt(fields.get("XMP ModifyDate")),
    )
    if xc and xm and abs((xm - xc).total_seconds()) > 60 and not (original and modified):
        res.findings.append(Finding("medium", "XMP modify date differs from its create date."))

    # 4. Camera fields / ISO (README: ISO value indicates original capture)
    make = fields.get("Image Make") or fields.get("Image Model")
    iso = fields.get("EXIF ISOSpeedRatings") or fields.get("EXIF PhotographicSensitivity")
    if make and not iso:
        res.findings.append(
            Finding("low", f"Camera ({make}) recorded but the ISO value is missing.")
        )
    elif iso:
        res.findings.append(
            Finding("info", f"Camera ISO {iso} present ({make or 'unknown camera'}).")
        )
    if make and not original:
        res.findings.append(Finding("low", "Camera make present but capture timestamp is missing."))
    if not has_exif and not xmp and doc.pages[0].is_jpeg:
        res.findings.append(
            Finding("info", "No camera metadata (common for scans, screenshots and chat apps).")
        )

    # 5. EXIF thumbnail vs image
    if thumb and pil is not None:
        sim = _thumbnail_similarity(thumb, pil)
        if sim is not None:
            res.metrics["thumbnail_similarity"] = round(sim, 3)
            if sim < 0.55:
                res.findings.append(
                    Finding(
                        "high",
                        "Embedded EXIF thumbnail does not match the picture: the image was "
                        "changed after the thumbnail was written.",
                    )
                )

    # 6. JPEG quality (informational; used by the compression modules)
    if pil is not None and getattr(pil, "quantization", None):
        q = estimate_jpeg_quality(pil.quantization)
        if q is not None:
            res.metrics["jpeg_quality"] = q
            res.findings.append(Finding("info", f"JPEG quality is approximately {q}."))
    if "GPS GPSLatitude" in fields:
        res.findings.append(Finding("info", "Contains GPS location data."))


def _extract_xmp(data: bytes) -> str | None:
    start = data.find(b"<x:xmpmeta")
    if start < 0:
        return None
    end = data.find(b"</x:xmpmeta>", start)
    if end < 0:
        return None
    return data[start : end + 12].decode("utf-8", errors="ignore")


def _parse_exif_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.strptime(v.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _parse_xmp_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.strip()[:19])
    except ValueError:
        return None


def _human_delta(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)} min"
    if seconds < 86400 * 2:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.0f} days"


def _thumbnail_similarity(thumb_bytes: bytes, pil: Image.Image) -> float | None:
    from skimage.metrics import structural_similarity

    t = cv2.imdecode(np.frombuffer(thumb_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if t is None or min(t.shape) < 16:
        return None
    # Trim letterbox bars that some cameras add to keep a fixed thumbnail size
    rows = np.where(t.std(axis=1) > 3)[0]
    cols = np.where(t.std(axis=0) > 3)[0]
    if rows.size < 8 or cols.size < 8:
        return None
    t = t[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
    main = np.asarray(pil.convert("L"))  # raw (un-rotated) orientation, like the thumbnail
    main_s = cv2.resize(main, (t.shape[1], t.shape[0]), interpolation=cv2.INTER_AREA)
    if abs(main.shape[1] / main.shape[0] - t.shape[1] / t.shape[0]) > 0.15:
        return 0.0  # aspect ratio changed => image was cropped after the thumbnail was made
    return float(structural_similarity(main_s, t, data_range=255, win_size=7))


def estimate_jpeg_quality(qtables: dict[int, list[int]]) -> int | None:
    """Estimate the IJG quality factor from the luminance quantisation table."""
    q0 = qtables.get(0)
    if not q0 or len(q0) != 64:
        return None
    q = np.array(q0, dtype=np.float64)
    # Pillow returns tables in zig-zag order; the mean ratio is order independent
    ratio = float(np.mean(q) / np.mean(_IJG_LUMA))
    scale = ratio * 100.0
    quality = (200.0 - scale) / 2.0 if scale <= 100 else 5000.0 / scale
    return int(np.clip(round(quality), 1, 100))


# --------------------------------------------------------------------------------------------
# PDFs


def _analyse_pdf(doc: Document, res: ModuleResult) -> None:
    import pymupdf as fitz

    res.confidence = 0.9
    pdf = fitz.open(stream=doc.data, filetype="pdf")
    meta = {k: v for k, v in (pdf.metadata or {}).items() if v}
    res.metrics["fields"] = {f"PDF {k}": str(v)[:200] for k, v in meta.items()}
    res.metrics["fields"]["PDF pages"] = str(pdf.page_count)

    tools = f"{meta.get('creator', '')} | {meta.get('producer', '')}".lower()
    editor = next((e for e in PDF_EDITORS if e in tools), None)
    if editor:
        res.findings.append(Finding("medium", f"PDF was produced or edited with {editor.title()}."))

    created, modified = _pdf_date(meta.get("creationDate")), _pdf_date(meta.get("modDate"))
    if created and modified and abs((modified - created).total_seconds()) > 60:
        res.findings.append(
            Finding(
                "medium",
                f"PDF modified {_human_delta(abs((modified - created).total_seconds()))} after "
                f"creation ({created:%Y-%m-%d %H:%M} -> {modified:%Y-%m-%d %H:%M}).",
            )
        )

    revisions = _incremental_updates(pdf, doc.data)
    res.metrics["incremental_updates"] = revisions
    if revisions > 0:
        res.findings.append(
            Finding(
                "medium" if revisions < 3 else "high",
                f"File was re-saved {revisions} time(s) after it was first written "
                "(incremental updates can change content while keeping the original bytes).",
            )
        )

    try:
        if pdf.get_sigflags() > 0:
            res.findings.append(
                Finding("info", "Contains digital signature fields (signature not validated).")
            )
    except Exception:  # noqa: BLE001
        pass
    if b"/JavaScript" in doc.data or b"/Launch" in doc.data:
        res.findings.append(Finding("low", "PDF contains embedded scripts or launch actions."))

    pages_by_index = {p.index: p for p in doc.pages}
    for pno in range(min(pdf.page_count, len(doc.pages) or 1)):
        page = pdf[pno]
        img_page = pages_by_index.get(pno)
        if img_page is None:
            continue
        ih, iw = img_page.shape
        sx, sy = iw / page.rect.width, ih / page.rect.height
        _pdf_page_checks(page, pno, sx, sy, res)
    pdf.close()


def _incremental_updates(pdf, data: bytes) -> int:
    count = getattr(pdf, "version_count", None)
    if isinstance(count, int) and count >= 1:
        return count - 1
    eofs = data.count(b"%%EOF")
    linearized = b"/Linearized" in data[:4096]
    return max(0, eofs - 1 - (1 if linearized else 0))


def _pdf_date(v: str | None) -> datetime | None:
    if not v:
        return None
    m = re.match(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?", v)
    if not m:
        return None
    parts = [int(p) if p else d for p, d in zip(m.groups(), (1970, 1, 1, 0, 0, 0), strict=True)]
    try:
        return datetime(*parts)
    except ValueError:
        return None


def _font_family(name: str) -> str:
    name = name.split("+", 1)[-1]  # strip subset prefix ABCDEF+
    name = re.split(r"[-,]", name)[0]
    return re.sub(r"(MT|PS|Std|Pro)$", "", name).lower()


def _pdf_page_checks(page, pno: int, sx: float, sy: float, res: ModuleResult) -> None:
    import pymupdf as fitz

    def box(rect, label: str, score: float = 1.0) -> Box:
        return Box(
            pno,
            int(rect.x0 * sx),
            int(rect.y0 * sy),
            int(rect.width * sx),
            int(rect.height * sy),
            label,
            score,
        )

    page_area = abs(page.rect.width * page.rect.height) or 1.0
    image_rects = []
    for img in page.get_images(full=True):
        with contextlib.suppress(Exception):
            image_rects += page.get_image_rects(img[0])
    scanned = any(abs(r.width * r.height) / page_area > 0.85 for r in image_rects)

    # Visible text spans (ignore invisible OCR layers, render mode 3)
    spans = []
    try:
        for s in page.get_texttrace():
            if s.get("type") != 3 and s.get("opacity", 1) > 0.1:
                text = "".join(chr(c[0]) for c in s.get("chars", []) if c[0] > 31).strip()
                if text:
                    spans.append((fitz.Rect(s["bbox"]), text))
    except Exception:  # noqa: BLE001
        pass

    # White boxes drawn over content ("whiteout") and text placed on top of them
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001
        drawings = []
    for d in drawings:
        fill = d.get("fill")
        rect = d.get("rect")
        if not fill or rect is None or d.get("fill_opacity", 1) < 0.9:
            continue
        area = abs(rect.width * rect.height)
        if min(fill) < 0.94 or area < 20 or area / page_area > 0.5:
            continue
        over_image = any(rect.intersects(r) for r in image_rects)
        text_on_top = [t for r, t in spans if rect.intersects(r)]
        if over_image and text_on_top:
            res.findings.append(
                Finding(
                    "high",
                    f"Page {pno + 1}: a white box masks part of the scan and new text "
                    f'"{" ".join(text_on_top)[:40]}" is written over it.',
                    pno,
                )
            )
            res.boxes.append(box(rect, "whiteout + overlaid text"))
        elif over_image:
            res.findings.append(
                Finding("medium", f"Page {pno + 1}: a white box hides part of the scan.", pno)
            )
            res.boxes.append(box(rect, "whiteout", 0.7))

    # Visible digital text sitting on a scanned page
    if scanned and spans:
        sample = " ".join(t for _, t in spans)[:50]
        res.findings.append(
            Finding(
                "medium",
                f'Page {pno + 1}: visible digital text over a scanned image ("{sample}").',
                pno,
            )
        )
        for r, _ in spans[:10]:
            res.boxes.append(box(r, "text over scan", 0.6))

    # Mixed fonts / sizes inside one line - typical of a value typed over an original
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:  # noqa: BLE001
        blocks = []
    mixed = 0
    for b in blocks:
        for line in b.get("lines", []):
            ss = [
                s
                for s in line.get("spans", [])
                if re.search(r"[A-Za-z0-9]", s.get("text", ""))
                and not any(f in s.get("font", "").lower() for f in SYMBOL_FONTS)
            ]
            if len(ss) < 2:
                continue
            fams = [_font_family(s.get("font", "")) for s in ss]
            sizes = [round(s.get("size", 0), 1) for s in ss]
            main_fam = max(set(fams), key=fams.count)
            main_size = max(set(sizes), key=sizes.count)
            for s, fam, size in zip(ss, fams, sizes, strict=True):
                odd_font = fam != main_fam
                odd_size = abs(size - main_size) > 0.6
                if (odd_font or odd_size) and len(s["text"].strip()) <= 40:
                    mixed += 1
                    if mixed <= 8:
                        res.boxes.append(box(fitz.Rect(s["bbox"]), "font mismatch", 0.6))
    if mixed:
        res.findings.append(
            Finding(
                "medium" if mixed >= 3 else "low",
                f"Page {pno + 1}: {mixed} text fragment(s) use a different font or size than "
                "the rest of their line.",
                pno,
            )
        )

    # Annotation overlays
    try:
        annots = list(page.annots() or [])
    except Exception:  # noqa: BLE001
        annots = []
    overlays = [a for a in annots if a.type[1] in ("FreeText", "Square", "Stamp", "Ink", "Redact")]
    if overlays:
        res.findings.append(
            Finding(
                "medium",
                f"Page {pno + 1}: {len(overlays)} annotation overlay(s) "
                f"({', '.join(sorted({a.type[1] for a in overlays}))}) may hide or add content.",
                pno,
            )
        )
        for a in overlays[:6]:
            res.boxes.append(box(a.rect, f"annotation ({a.type[1]})", 0.7))
