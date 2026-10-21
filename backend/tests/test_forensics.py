"""Unit tests for the forensic engine (no web layer)."""

import io
import random

import cv2
import fitz
import numpy as np
import pytest
from PIL import Image

from docauth import synth
from docauth.forensics import Engine, TemplateRef, UnsupportedFile, load_document
from docauth.forensics.modules.base import AnalysisContext
from docauth.forensics.modules.copymove import CopyMoveModule
from docauth.forensics.modules.jpeg import JpegModule
from docauth.forensics.modules.metadata import MetadataModule, estimate_jpeg_quality
from docauth.forensics.modules.template import TemplateModule
from docauth.forensics.util import jpeg_grid_offset, luma

CTX = AnalysisContext()


def _doc(data: bytes, name="x.jpg"):
    return load_document(data, name)


def test_sniffing_rejects_non_documents():
    with pytest.raises(UnsupportedFile):
        load_document(b"GIF89a....", "a.gif")
    with pytest.raises(UnsupportedFile):
        load_document(b"<html>", "a.jpg")


def test_jpeg_quality_estimate():
    img = synth.natural_image(1, (256, 256))
    for q in (60, 75, 90):
        pil = Image.open(io.BytesIO(synth.jpeg_bytes(img, q)))
        assert abs(estimate_jpeg_quality(pil.quantization) - q) <= 3


def test_grid_offset_detects_crop():
    img = synth.jpeg(synth.natural_image(2, (512, 512)), 80)
    dy, dx, s = jpeg_grid_offset(luma(img))
    assert (dy, dx) == (0, 0) and s > 0.1
    dy, dx, s = jpeg_grid_offset(luma(img[3:, 5:]))
    assert (dy, dx) == (5, 3) and s > 0.1


def test_metadata_flags_editing_software_and_dates():
    img = Image.fromarray(synth.natural_image(3, (240, 320))[:, :, ::-1])
    exif = Image.Exif()
    exif[0x0131] = "Adobe Photoshop 25.0 (Windows)"  # Software
    exif[0x010F] = "Canon"  # Make
    exif[0x0132] = "2024:05:02 10:00:00"  # DateTime (modified)
    exif.get_ifd(0x8769)[0x9003] = "2024:01:01 09:00:00"  # DateTimeOriginal
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, exif=exif)
    r = MetadataModule().run(_doc(buf.getvalue()), CTX)
    msgs = " ".join(f.message for f in r.findings)
    assert "Photoshop" in msgs
    assert "after it was captured" in msgs
    assert "ISO" in msgs  # camera recorded but ISO missing
    assert r.suspicion > 0.8


def test_metadata_clean_image_not_flagged(natural_jpeg):
    r = MetadataModule().run(_doc(natural_jpeg), CTX)
    assert r.suspicion < 0.2


def _pdf_with_whiteout() -> bytes:
    scan = synth.jpeg_bytes(synth.render_document(seed=5).image, 85)
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=scan)
    rect = fitz.Rect(300, 300, 420, 320)
    page.draw_rect(rect, color=None, fill=(1, 1, 1))
    page.insert_text((302, 315), "Rs. 9,90,000", fontsize=11, fontname="helv")
    return pdf.tobytes()


def test_pdf_whiteout_and_overlay_detected():
    data = _pdf_with_whiteout()
    doc = load_document(data, "cert.pdf")
    assert doc.kind == "pdf" and doc.pages[0].source == "pdf-embedded"
    r = MetadataModule().run(doc, CTX)
    msgs = " ".join(f.message for f in r.findings)
    assert "white box" in msgs
    assert r.suspicion > 0.8
    assert r.boxes


def test_pdf_incremental_update_detected(tmp_path):
    path = tmp_path / "issued.pdf"
    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Annual income: Rs. 1,20,000", fontsize=12)
    pdf.save(path)
    pdf.close()
    clean = MetadataModule().run(load_document(path.read_bytes(), "issued.pdf"), CTX)
    assert clean.metrics["incremental_updates"] == 0

    pdf = fitz.open(path)  # a forger edits the issued file and saves incrementally
    pdf[0].insert_text((72, 100), "Revised: Rs. 9,20,000", fontsize=12)
    pdf.saveIncr()
    pdf.close()
    r = MetadataModule().run(load_document(path.read_bytes(), "issued.pdf"), CTX)
    assert r.metrics["incremental_updates"] >= 1
    assert any("re-saved" in f.message for f in r.findings)


def test_copy_move_detected_in_photo():
    nat = synth.natural_image(11)
    cm = nat.copy()
    cm[400:540, 600:780] = nat[100:240, 150:330]
    r = CopyMoveModule().run(_doc(synth.jpeg_bytes(cm, 92)), CTX)
    assert r.suspicion > 0.6
    assert len(r.boxes) >= 2
    clean = CopyMoveModule().run(_doc(synth.jpeg_bytes(nat, 92)), CTX)
    assert clean.suspicion < 0.1


def test_copy_move_ignores_repeated_words_in_documents():
    for seed in (1, 2, 3):
        data, _, _ = synth.make_sample(seed, tampered=False)
        r = CopyMoveModule().run(_doc(data), CTX)
        assert r.suspicion < 0.3, r.findings


def test_splice_from_lower_quality_jpeg_detected():
    nat = synth.jpeg(synth.natural_image(12), 90)
    donor = synth.jpeg(synth.natural_image(13), 55)
    sp = nat.copy()
    sp[200:360, 300:500] = donor[200:360, 300:500]
    r = JpegModule().run(_doc(synth.jpeg_bytes(sp, 90)), CTX)
    assert r.suspicion > 0.6
    b = r.boxes[0]
    assert b.x < 500 and b.x + b.w > 300 and b.y < 360 and b.y + b.h > 200
    clean = JpegModule().run(_doc(synth.jpeg_bytes(nat, 90)), CTX)
    assert clean.suspicion < 0.3


def test_template_module_finds_added_content():
    ref = synth.render_document(seed=10, layout_seed=77)
    other = synth.render_document(seed=11, layout_seed=77)
    rng = random.Random(0)
    scanned = synth.jpeg(synth.scan_effects(other.image, rng, 0.6), 90)
    # slight rotation/scale like a real scan; alignment must undo it
    h, w = scanned.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 1.2, 0.97)
    scanned = cv2.warpAffine(scanned, M, (w, h), borderValue=(240, 240, 240))
    tpl = TemplateRef(1, "ref", ref.image, ref.variable_regions())
    ok = TemplateModule().run(_doc(synth.jpeg_bytes(scanned, 92)), AnalysisContext(template=tpl))
    assert ok.status == "ok" and not ok.boxes, ok.boxes

    forged = scanned.copy()
    cv2.putText(
        forged, "CLASS: FIRST", (200, int(h * 0.85)), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (10, 10, 10), 3
    )
    bad = TemplateModule().run(_doc(synth.jpeg_bytes(forged, 92)), AnalysisContext(template=tpl))
    assert bad.suspicion > 0.6
    assert any(b.label in ("added content", "altered content") for b in bad.boxes)


def test_template_mismatch_reported():
    a = synth.render_document(seed=1, layout_seed=1)
    tpl = TemplateRef(1, "other", synth.natural_image(3, (1000, 700)), [])
    r = TemplateModule().run(_doc(synth.jpeg_bytes(a.image, 92)), AnalysisContext(template=tpl))
    assert r.suspicion >= 0.5
    assert "could not be aligned" in r.summary


def test_engine_report_shape_and_ordering(tmp_path, natural_jpeg):
    eng = Engine()
    clean = eng.analyze(_doc(natural_jpeg))
    nat = synth.natural_image(7, (480, 640))
    cm = nat.copy()
    cm[300:420, 400:560] = nat[40:160, 60:220]
    forged = eng.analyze(_doc(synth.jpeg_bytes(cm, 92)))
    assert forged.score < clean.score
    assert clean.verdict == "authentic"
    d = clean.save(tmp_path / "out")
    assert (tmp_path / "out" / d["pages"][0]["image"]).exists()
    for m in d["modules"]:
        assert 0 <= m["suspicion"] <= 1
        assert 0 <= m["score10"] <= 10
        for a in m["artifacts"]:
            assert (tmp_path / "out" / a["file"]).exists()
    skipped = {m["key"]: m for m in d["modules"] if m["status"] == "skipped"}
    assert "cnn" in skipped and "not installed" in skipped["cnn"]["summary"]


def test_module_failure_is_isolated():
    class Boom(MetadataModule):
        key = "boom"

        def run(self, doc, ctx):
            raise RuntimeError("kaboom")

    eng = Engine(modules=[Boom(), CopyMoveModule()], calibration={})
    rep = eng.analyze(_doc(synth.jpeg_bytes(synth.natural_image(1, (256, 256)), 90)))
    assert rep.modules[0].status == "error" and "kaboom" in rep.modules[0].summary
    assert rep.modules[1].status == "ok"


def test_large_images_are_downscaled():
    big = np.full((5000, 3000, 3), 200, np.uint8)
    doc = load_document(cv2.imencode(".png", big)[1].tobytes(), "big.png")
    assert max(doc.pages[0].shape) == 4096 and doc.pages[0].resampled
    assert doc.notes
