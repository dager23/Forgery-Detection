"""Synthetic certificate generator + realistic forgery simulator.

Used for unit tests, demo samples, template ignore-regions and as a fallback/augmenting
training set. The forgery pipeline mimics how real document forgeries are produced:

    render -> scan effects -> JPEG (q1) -> *edit in an image editor* -> JPEG (q2)

Authentic samples go through the same compression chain (sometimes twice) so models can't
cheat by learning "double-compressed == fake".
"""

from __future__ import annotations

import glob
import os
import random
from dataclasses import dataclass, field
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FIRST = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Ananya",
    "Diya",
    "Ishaan",
    "Kavya",
    "Rohan",
    "Sneha",
    "Arjun",
    "Meera",
    "Priya",
    "Rahul",
    "Neha",
    "Siddharth",
    "Pooja",
    "Karan",
    "Nisha",
    "Yash",
    "Tanvi",
    "Harsh",
    "Riya",
    "Manish",
    "Lakshmi",
    "Farhan",
    "Gurpreet",
]
LAST = [
    "Sharma",
    "Patel",
    "Iyer",
    "Reddy",
    "Shah",
    "Gupta",
    "Nair",
    "Khan",
    "Singh",
    "Das",
    "Mehta",
    "Joshi",
    "Kulkarni",
    "Banerjee",
    "Chopra",
    "Menon",
    "Verma",
    "Pillai",
]
STATES = [
    "MAHARASHTRA",
    "GUJARAT",
    "KARNATAKA",
    "TAMIL NADU",
    "KERALA",
    "RAJASTHAN",
    "UTTAR PRADESH",
    "WEST BENGAL",
    "TELANGANA",
    "PUNJAB",
    "ODISHA",
    "BIHAR",
]
DOC_TYPES = [
    "INCOME CERTIFICATE",
    "CASTE CERTIFICATE",
    "DOMICILE CERTIFICATE",
    "BIRTH CERTIFICATE",
    "DEGREE CERTIFICATE",
    "STATEMENT OF MARKS",
]
CITIES = [
    "Pune",
    "Mumbai",
    "Ahmedabad",
    "Bengaluru",
    "Chennai",
    "Kochi",
    "Jaipur",
    "Lucknow",
    "Kolkata",
    "Hyderabad",
    "Amritsar",
    "Bhubaneswar",
    "Patna",
    "Vellore",
]


@lru_cache
def font_files() -> list[str]:
    dirs = [
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts"),
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.fonts"),
        "/Library/Fonts",
        "/System/Library/Fonts",
    ]
    wanted = (
        "arial",
        "times",
        "calibri",
        "cambria",
        "georgia",
        "verdana",
        "tahoma",
        "segoeui",
        "dejavusans",
        "dejavuserif",
        "liberation",
        "notosans-",
        "notoserif-",
        "cour",
        "trebuc",
        "garamond",
        "bookos",
        "constan",
        "corbel",
        "candara",
    )
    found = []
    for d in dirs:
        for f in glob.glob(os.path.join(d, "**", "*.tt[fc]"), recursive=True):
            name = os.path.basename(f).lower()
            if any(name.startswith(w) for w in wanted) and "symbol" not in name:
                found.append(f)
    return sorted(set(found))


def get_font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


@dataclass
class SynthDoc:
    image: np.ndarray  # BGR uint8
    doc_type: str
    layout_seed: int
    fields: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)  # value boxes
    words: list[tuple[int, int, int, int]] = field(default_factory=list)  # all text boxes
    seal_box: tuple[int, int, int, int] | None = None
    signature_box: tuple[int, int, int, int] | None = None
    body_font: str | None = None
    issuer: str = ""

    def variable_regions(self, pad: int = 6) -> list[dict[str, float]]:
        """Normalised boxes of fields that differ between genuine copies (for templates)."""
        h, w = self.image.shape[:2]
        out = []
        for name, (x, y, bw, bh) in self.fields.items():
            out.append(
                {
                    "x": max(0, x - pad) / w,
                    "y": max(0, y - pad) / h,
                    "w": min(w, bw + 2 * pad + 220) / w,
                    "h": (bh + 2 * pad) / h,
                    "label": name,
                }
            )
        if self.signature_box:
            x, y, bw, bh = self.signature_box
            out.append(
                {
                    "x": (x - pad) / w,
                    "y": (y - pad) / h,
                    "w": (bw + 2 * pad) / w,
                    "h": (bh + 2 * pad) / h,
                    "label": "signature",
                }
            )
        return out


def _random_values(rng: random.Random, doc_type: str) -> dict[str, str]:
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"

    def date(y0: int, y1: int) -> str:
        return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(y0, y1)}"

    street = rng.choice(["MG Road", "Station Road", "Nehru Nagar", "Gandhi Chowk", "Civil Lines"])
    v = {
        "Name": name,
        "Father's Name": f"{rng.choice(FIRST)} {name.split()[-1]}",
        "Date of Birth": date(1975, 2008),
        "Certificate No.": f"{rng.choice('ABCDEFGHJK')}{rng.choice('LMNPQRSTUV')}/"
        f"{rng.randint(2018, 2026)}/{rng.randint(10000, 99999)}",
        "Address": f"{rng.randint(1, 450)}, {street}, {rng.choice(CITIES)}",
        "Date of Issue": date(2019, 2026),
    }
    if "INCOME" in doc_type:
        v["Annual Income"] = f"Rs. {rng.randint(40, 990) * 1000:,}/-"
    elif "CASTE" in doc_type:
        v["Category"] = rng.choice(["OBC", "SC", "ST", "VJNT", "SBC"])
    elif "MARKS" in doc_type or "DEGREE" in doc_type:
        v["CGPA"] = f"{rng.uniform(6.0, 9.9):.2f}"
        v["Seat No."] = f"{rng.randint(100000, 999999)}"
    return v


def render_document(
    seed: int | None = None,
    layout_seed: int | None = None,
    size: tuple[int, int] = (1240, 1754),
    values: dict[str, str] | None = None,
) -> SynthDoc:
    """Render a certificate. Docs sharing ``layout_seed`` share a template (fixed parts)."""
    rng = random.Random(seed)
    layout_seed = layout_seed if layout_seed is not None else rng.randrange(1 << 30)
    lay = random.Random(layout_seed)
    w, h = size
    fonts = font_files()
    f_title = lay.choice(fonts) if fonts else None
    f_body = lay.choice(fonts) if fonts else None
    doc_type = lay.choice(DOC_TYPES)
    state = lay.choice(STATES)
    paper = tuple(lay.randint(236, 252) for _ in range(3))
    ink = tuple(lay.randint(0, 50) for _ in range(3))
    accent = lay.choice([(20, 40, 120), (120, 20, 20), (10, 80, 40), (60, 20, 100)])

    img = Image.new("RGB", (w, h), paper)
    d = ImageDraw.Draw(img)
    words: list[tuple[int, int, int, int]] = []

    def text(xy, s, font, fill):
        d.text(xy, s, font=font, fill=fill)
        x0, y0, x1, y1 = (int(round(v)) for v in d.textbbox(xy, s, font=font))
        words.append((x0, y0, x1 - x0, y1 - y0))
        return x0, y0, x1, y1

    m = lay.randint(50, 80)
    d.rectangle([m, m, w - m, h - m], outline=accent, width=lay.randint(3, 6))
    d.rectangle([m + 12, m + 12, w - m - 12, h - m - 12], outline=accent, width=1)

    # Emblem (fixed) + headers
    cx, cy, r = w // 2, m + 120, 55
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent, width=4)
    for k in range(12):
        a = k * np.pi / 6
        d.line(
            [cx, cy, cx + int(r * 0.8 * np.cos(a)), cy + int(r * 0.8 * np.sin(a))],
            fill=accent,
            width=2,
        )
    ft_big = get_font(f_title, lay.randint(40, 50))
    ft_mid = get_font(f_title, lay.randint(28, 34))
    y = cy + r + 25
    for s, font in ((f"GOVERNMENT OF {state}", ft_mid), (doc_type, ft_big)):
        tw = d.textlength(s, font=font)
        _, _, _, y1 = text(((w - tw) / 2, y), s, font, accent)
        y = y1 + 22
    officer = lay.choice(["Tahsildar", "District Collector", "Registrar", "Sub-Divisional Officer"])
    office = f"Office of the {officer}, {lay.choice(CITIES)}"
    fs = get_font(f_body, 24)
    tw = d.textlength(office, font=fs)
    text(((w - tw) / 2, y), office, fs, ink)
    y += 70
    d.line([m + 60, y, w - m - 60, y], fill=accent, width=2)
    y += 40

    vals = values or _random_values(rng, doc_type)
    fb = get_font(f_body, lay.randint(26, 30))
    fv = get_font(f_body, lay.randint(26, 30))
    label_x = m + 90
    value_x = label_x + lay.randint(300, 360)
    fields = {}
    line_h = lay.randint(58, 70)
    for label, value in vals.items():
        text((label_x, y), f"{label}", fb, ink)
        text((value_x - 30, y), ":", fb, ink)
        x0, y0, x1, y1 = text((value_x, y), value, fv, ink)
        fields[label] = (x0, y0, x1 - x0, y1 - y0)
        y += line_h

    # Fixed body paragraph
    y += 20
    para = (
        "This is to certify that the particulars given above have been verified from the "
        "records maintained in this office and are found to be correct. This certificate is "
        "issued for official purposes and is valid subject to verification."
    )
    fp = get_font(f_body, 24)
    line = ""
    for word in para.split():
        trial = f"{line} {word}".strip()
        if d.textlength(trial, font=fp) > w - 2 * label_x:
            text((label_x, y), line, fp, ink)
            y += 38
            line = word
        else:
            line = trial
    if line:
        text((label_x, y), line, fp, ink)
        y += 38

    # Seal (fixed design) and signature (variable stroke)
    sy = min(h - m - 260, y + 120)
    sx = m + 170
    sr = 85
    d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], outline=accent, width=5)
    d.ellipse([sx - sr + 18, sy - sr + 18, sx + sr - 18, sy + sr - 18], outline=accent, width=2)
    fseal = get_font(f_title, 20)
    seal_txt = "SEAL"
    tw = d.textlength(seal_txt, font=fseal)
    d.text((sx - tw / 2, sy - 12), seal_txt, font=fseal, fill=accent)
    seal_box = (sx - sr, sy - sr, 2 * sr, 2 * sr)

    sig_x, sig_y = w - m - 420, sy - 40
    pts = []
    srng = random.Random(seed)
    px, py = sig_x, sig_y + 40
    for _ in range(srng.randint(5, 9)):
        nx, ny = px + srng.randint(25, 55), sig_y + srng.randint(0, 80)
        pts.append(((px, py), (nx, ny)))
        px, py = nx, ny
    for a, b in pts:
        d.line([a, b], fill=(20, 30, 110), width=3)
    signature_box = (sig_x, sig_y, max(40, px - sig_x), 90)
    fsig = get_font(f_body, 24)
    text((sig_x, sig_y + 110), "Authorised Signatory", fsig, ink)

    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    return SynthDoc(
        bgr, doc_type, layout_seed, fields, words, seal_box, signature_box, f_body, state.title()
    )


def scan_effects(img: np.ndarray, rng: random.Random, strength: float = 1.0) -> np.ndarray:
    """Paper texture, illumination gradient, slight blur and sensor noise."""
    h, w = img.shape[:2]
    out = img.astype(np.float32)
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    grad = (
        1.0
        - strength * rng.uniform(0, 0.08) * (gx / w)
        - strength * rng.uniform(0, 0.06) * (gy / h)
    )
    out *= grad[..., None]
    tex = cv2.resize(
        np.random.default_rng(rng.randrange(1 << 30))
        .normal(0, 1, (h // 8 + 1, w // 8 + 1))
        .astype(np.float32),
        (w, h),
    )
    out += strength * rng.uniform(1.0, 3.0) * tex[..., None]
    if rng.random() < 0.7:
        out = cv2.GaussianBlur(out, (0, 0), rng.uniform(0.4, 0.9))
    noise = np.random.default_rng(rng.randrange(1 << 30)).normal(
        0, strength * rng.uniform(1.2, 3.0), out.shape
    )
    out += noise.astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def jpeg(img: np.ndarray, q: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def jpeg_bytes(img: np.ndarray, q: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(q)])
    assert ok
    return buf.tobytes()


def _bg_color(img: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    pad = 6
    H, W = img.shape[:2]
    y0, y1 = max(0, y - pad), min(H, y + h + pad)
    x0, x1 = max(0, x - pad), min(W, x + w + pad)
    ring = np.concatenate([img[y0:y, x0:x1].reshape(-1, 3), img[y + h : y1, x0:x1].reshape(-1, 3)])
    if ring.size == 0:
        return np.array([245, 245, 245], np.uint8)
    lum = ring.mean(axis=1)
    light = ring[lum > np.percentile(lum, 40)]
    return np.median(light if light.size else ring, axis=0).astype(np.uint8)


TAMPER_KINDS = ("text_replace", "copy_move", "splice", "erase", "insert_text")


def tamper(img: np.ndarray, doc: SynthDoc, rng: random.Random, kind: str | None = None):
    """Apply one realistic edit. Returns (edited BGR, mask uint8 {0,1}, kind)."""
    kind = kind or rng.choice(TAMPER_KINDS)
    out = img.copy()
    mask = np.zeros(img.shape[:2], np.uint8)
    H, W = img.shape[:2]
    fields = list(doc.fields.items())
    fonts = font_files()

    if kind in ("text_replace", "copy_move") and fields:
        label, (x, y, w, h) = rng.choice(fields)
        pad = 4
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad + rng.randint(0, 60)), min(H, y + h + pad)
        bg = _bg_color(out, x, y, w, h)
        if rng.random() < 0.5:
            out[y0:y1, x0:x1] = bg  # flat fill ("white box")
        else:
            m = np.zeros((H, W), np.uint8)
            m[y0:y1, x0:x1] = 255
            out = cv2.inpaint(out, m, 5, cv2.INPAINT_TELEA)
        mask[y0:y1, x0:x1] = 1
        if kind == "text_replace":
            new = _mutate_value(doc, label, rng)
            pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
            dr = ImageDraw.Draw(pil)
            # half the time the forger finds the original font (harder to spot)
            same = rng.random() < 0.5 or not fonts
            fpath = doc.body_font if same else rng.choice(fonts)
            size = max(14, int(h * rng.uniform(1.0, 1.25)))
            font = get_font(fpath, size)
            ink = tuple(int(c) for c in rng.choice([(10, 10, 10), (30, 30, 40), (20, 20, 90)]))
            dr.text((x + rng.randint(-2, 3), y + rng.randint(-3, 3)), new, font=font, fill=ink)
            tx0, ty0, tx1, ty1 = dr.textbbox((x, y), new, font=font)
            out = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
            mask[max(0, ty0 - 2) : ty1 + 3, max(0, tx0 - 2) : tx1 + 3] = 1
        else:
            # copy another value (e.g. a different number) into this field
            others = [f for f in fields if f[0] != label] or fields
            _, (sx, sy, sw, sh) = rng.choice(others)
            patch = img[max(0, sy - 2) : sy + sh + 2, max(0, sx - 2) : sx + sw + 2]
            ph, pw = patch.shape[:2]
            ty, tx = max(0, y - 2), max(0, x - 2)
            ph, pw = min(ph, H - ty), min(pw, W - tx)
            out[ty : ty + ph, tx : tx + pw] = patch[:ph, :pw]
            mask[ty : ty + ph, tx : tx + pw] = 1
    elif kind == "splice":
        # paste a seal/signature/photo-like patch that has its own compression history
        donor = render_document(rng.randrange(1 << 30)).image
        donor = scan_effects(donor, rng, 0.6)
        donor = jpeg(donor, rng.randint(40, 75))
        box = doc.seal_box if rng.random() < 0.5 and doc.seal_box else None
        if box is None:
            bw, bh = rng.randint(120, 320), rng.randint(60, 200)
            bx, by = rng.randint(80, W - bw - 80), rng.randint(300, H - bh - 120)
        else:
            bx, by, bw, bh = box
            bx += rng.randint(-40, 40)
            by += rng.randint(-40, 40)
            bx, by = max(0, bx), max(0, by)
            bw, bh = min(bw, W - bx), min(bh, H - by)
        dx, dy = rng.randint(0, donor.shape[1] - bw - 1), rng.randint(0, donor.shape[0] - bh - 1)
        patch = donor[dy : dy + bh, dx : dx + bw]
        if rng.random() < 0.4:
            f = rng.uniform(0.8, 1.25)
            patch = cv2.resize(cv2.resize(patch, None, fx=f, fy=f), (bw, bh))
        out[by : by + bh, bx : bx + bw] = patch
        mask[by : by + bh, bx : bx + bw] = 1
    elif kind == "erase" and doc.words:
        x, y, w, h = rng.choice(doc.words)
        y0, y1, x0, x1 = max(0, y - 3), min(H, y + h + 3), max(0, x - 3), min(W, x + w + 3)
        m = np.zeros((H, W), np.uint8)
        m[y0:y1, x0:x1] = 255
        out = cv2.inpaint(out, m, 7, cv2.INPAINT_TELEA)
        mask[y0:y1, x0:x1] = 1
    else:  # insert_text
        kind = "insert_text"
        pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))
        dr = ImageDraw.Draw(pil)
        font = get_font(rng.choice(fonts) if fonts else None, rng.randint(22, 32))
        s = rng.choice(
            [
                "Remarks: Verified",
                "Endorsed",
                "Category: General",
                "Valid till 2031",
                "Income revised",
                "Duplicate copy",
                "Rank: 1",
            ]
        )
        x, y = rng.randint(120, W - 520), rng.randint(int(H * 0.55), H - 200)
        dr.text((x, y), s, font=font, fill=(20, 20, 30))
        x0, y0, x1, y1 = dr.textbbox((x, y), s, font=font)
        out = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        mask[max(0, y0 - 2) : y1 + 3, max(0, x0 - 2) : x1 + 3] = 1
    return out, mask, kind


def _mutate_value(doc: SynthDoc, label: str, rng: random.Random) -> str:
    if label == "Annual Income":
        return f"Rs. {rng.randint(20, 200) * 1000:,}/-"
    if label in ("Date of Birth", "Date of Issue"):
        return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1975, 2026)}"
    if label == "CGPA":
        return f"{rng.uniform(8.5, 9.99):.2f}"
    if label == "Category":
        return rng.choice(["OBC", "SC", "ST", "GENERAL"])
    if "Name" in label:
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    return "".join(rng.choice("0123456789") for _ in range(6))


def make_sample(seed: int, tampered: bool, size=(1240, 1754)):
    """Full pipeline -> (jpeg bytes, mask or None, meta)."""
    rng = random.Random(seed)
    doc = render_document(seed, size=size)
    img = scan_effects(doc.image, rng)
    q1 = rng.randint(70, 97)
    img = jpeg(img, q1)
    meta = {"q1": q1, "doc_type": doc.doc_type}
    mask = None
    if tampered:
        img, mask, kind = tamper(img, doc, rng)
        meta["kind"] = kind
    q2 = rng.randint(70, 97)
    if tampered or rng.random() < 0.5:
        meta["q2"] = q2
        data = jpeg_bytes(img, q2)
    else:
        data = jpeg_bytes(img, q1)  # identical re-encode of the same quality
    return data, mask, meta


def natural_image(seed: int, size: tuple[int, int] = (768, 1024)) -> np.ndarray:
    """A textured 'photo-like' image (multi-scale noise + shapes + sensor noise)."""
    g = np.random.default_rng(seed)
    h, w = size
    out = np.zeros((h, w, 3), np.float32)
    for s, amp in ((4, 90), (16, 40), (64, 20), (256, 10)):
        n = g.normal(0, 1, (max(2, h * s // 1024), max(2, w * s // 1024), 3)).astype(np.float32)
        out += amp * cv2.resize(n, (w, h), interpolation=cv2.INTER_CUBIC)
    out += 128
    for _ in range(12):
        c = tuple(int(v) for v in g.integers(0, 255, 3))
        cv2.ellipse(
            out,
            (int(g.integers(0, w)), int(g.integers(0, h))),
            (int(g.integers(10, 120)), int(g.integers(10, 120))),
            float(g.integers(0, 180)),
            0,
            360,
            c,
            -1,
        )
    out = cv2.GaussianBlur(out, (0, 0), 1.0)
    out += g.normal(0, 3.0, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)
