"""Turn uploaded bytes (image or PDF) into analysable pages."""

from __future__ import annotations

import io
import warnings

import cv2
import numpy as np
from PIL import Image, ImageOps

from docauth.forensics.types import Document, Page

MAX_SIDE = 4096  # analyse at native resolution up to this size
PDF_RENDER_DPI = 150
Image.MAX_IMAGE_PIXELS = 120_000_000  # guard against decompression bombs

SUPPORTED = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/tiff": "tiff",
    "image/bmp": "bmp",
    "image/webp": "webp",
    "application/pdf": "pdf",
}


class UnsupportedFile(ValueError):
    pass


def sniff_mime(data: bytes) -> str | None:
    """Identify the file type from magic bytes (never trust the extension/Content-Type)."""
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if data[:1024].lstrip().startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        return "application/pdf"
    return None


def _to_bgr(img: Image.Image) -> np.ndarray:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    if img.mode in ("I;16", "I;16B", "I;16L", "I"):
        arr = np.asarray(img, dtype=np.float32)
        arr = cv2.normalize(arr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    rgb = np.asarray(img.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _limit(image: np.ndarray) -> tuple[np.ndarray, bool, float]:
    h, w = image.shape[:2]
    side = max(h, w)
    if side <= MAX_SIDE:
        return image, False, 1.0
    scale = MAX_SIDE / side
    resized = cv2.resize(image, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    return resized, True, scale


def decode_image(data: bytes) -> tuple[np.ndarray, str, Image.Image]:
    """Decode an image, applying EXIF orientation so results match what users see."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Image.DecompressionBombWarning as e:
            raise UnsupportedFile("Image is too large to analyse safely") from e
        except Exception as e:  # noqa: BLE001 - PIL raises many types
            raise UnsupportedFile(f"Could not decode image: {e}") from e
    fmt = (img.format or "").lower()
    fmt = {"jpg": "jpeg", "mpo": "jpeg"}.get(fmt, fmt)
    oriented = ImageOps.exif_transpose(img) or img
    return _to_bgr(oriented), fmt, img


def load_image_document(data: bytes, filename: str, mime: str) -> Document:
    bgr, fmt, _ = decode_image(data)
    limited, resampled, scale = _limit(bgr)
    notes = []
    if resampled:
        notes.append(
            f"Image downscaled from {bgr.shape[1]}x{bgr.shape[0]} for analysis; "
            "compression-based evidence is weaker."
        )
    page = Page(0, limited, "raster", data, fmt, resampled, scale)
    return Document(filename, mime, "image", data, [page], 1, notes)


def load_pdf_document(data: bytes, filename: str, max_pages: int = 10) -> Document:
    import fitz  # PyMuPDF

    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise UnsupportedFile(f"Could not open PDF: {e}") from e
    if pdf.needs_pass:
        raise UnsupportedFile("PDF is password protected")
    notes: list[str] = []
    pages: list[Page] = []
    total = pdf.page_count
    if total == 0:
        raise UnsupportedFile("PDF has no pages")
    if total > max_pages:
        notes.append(f"Only the first {max_pages} of {total} pages were analysed.")
    for i in range(min(total, max_pages)):
        page = pdf[i]
        embedded = _dominant_embedded_image(pdf, page)
        if embedded is not None:
            raw, ext = embedded
            try:
                bgr, fmt, _ = decode_image(raw)
                limited, resampled, scale = _limit(bgr)
                pages.append(Page(i, limited, "pdf-embedded", raw, fmt, resampled, scale))
                continue
            except UnsupportedFile:
                pass  # fall back to rendering
        pix = page.get_pixmap(dpi=PDF_RENDER_DPI, alpha=False)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR if pix.n == 3 else cv2.COLOR_GRAY2BGR)
        limited, resampled, scale = _limit(bgr)
        pages.append(Page(i, limited, "pdf-render", None, "png", resampled, scale))
    pdf.close()
    return Document(filename, "application/pdf", "pdf", data, pages, total, notes)


def _dominant_embedded_image(pdf, page) -> tuple[bytes, str] | None:
    """If a page is essentially one scanned image, return that image's original bytes.

    Analysing the embedded JPEG directly preserves compression traces that a re-render destroys.
    """
    images = page.get_images(full=True)
    if len(images) != 1:
        return None
    xref = images[0][0]
    try:
        rects = page.get_image_rects(xref)
    except Exception:  # noqa: BLE001
        return None
    if not rects:
        return None
    page_area = abs(page.rect.width * page.rect.height) or 1.0
    covered = max(abs(r.width * r.height) for r in rects) / page_area
    if covered < 0.85:
        return None
    info = pdf.extract_image(xref)
    if not info or not info.get("image"):
        return None
    return info["image"], info.get("ext", "")


def load_document(data: bytes, filename: str, max_pages: int = 10) -> Document:
    mime = sniff_mime(data)
    if mime is None or mime not in SUPPORTED:
        raise UnsupportedFile("Unsupported file type. Upload a JPEG, PNG, TIFF, BMP, WebP or PDF.")
    if mime == "application/pdf":
        return load_pdf_document(data, filename, max_pages)
    return load_image_document(data, filename, mime)


def load_template_image(data: bytes) -> np.ndarray:
    """Templates may be uploaded as an image or a single-page PDF; return page 1 as BGR."""
    doc = load_document(data, "template", max_pages=1)
    return doc.pages[0].image
