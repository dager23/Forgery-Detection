"""Command line interface.

docauth analyze FILE [--template REF] [--json] [--out DIR]
docauth serve [--host 127.0.0.1] [--port 8000]
docauth create-admin --email you@example.com [--name NAME]
docauth seed-demo            # demo templates + sample genuine/forged documents
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

VERDICT_ICON = {"authentic": "ACCEPTED", "suspicious": "SUSPICIOUS", "tampered": "REJECTED"}


def _analyze(a: argparse.Namespace) -> int:
    from docauth.forensics import Engine, TemplateRef, load_document, load_template_image

    data = Path(a.file).read_bytes()
    doc = load_document(data, Path(a.file).name)
    template = None
    if a.template:
        regions = json.loads(Path(a.ignore).read_text()) if a.ignore else []
        template = TemplateRef(
            None, Path(a.template).stem, load_template_image(Path(a.template).read_bytes()), regions
        )
    report = Engine().analyze(doc, template)
    result = report.save(Path(a.out)) if a.out else report.to_dict()
    if a.json:
        print(json.dumps(result, indent=2))
        return 0
    print(
        f"\n{Path(a.file).name}: {VERDICT_ICON[report.verdict]}  "
        f"(authenticity {report.score:.0f}/100, {report.duration_ms} ms)"
    )
    print(f"{report.summary}\n")
    for m in result["modules"]:
        score = f"{m['score10']:>4.1f}/10" if m["status"] == "ok" else f"{m['status']:>7s}"
        print(f"  {m['title']:<30s} {score}  {m['summary']}")
        for f in m["findings"]:
            if f["severity"] in ("medium", "high"):
                print(f"      [{f['severity']}] {f['message']}")
    if a.out:
        print(f"\nArtifacts written to {a.out}")
    return 0


def _serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("docauth.main:app", host=a.host, port=a.port, reload=a.reload)
    return 0


def _create_admin(a: argparse.Namespace) -> int:
    from sqlalchemy import select

    from docauth.config import get_settings
    from docauth.db import Database
    from docauth.models import User
    from docauth.schemas import _check_password
    from docauth.security import hash_password

    settings = get_settings()
    settings.ensure_dirs()
    db = Database(settings.db_url)
    db.create_all()
    password = a.password or getpass.getpass("Password: ")
    try:
        _check_password(password)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    with db.session() as s:
        user = s.scalar(select(User).where(User.email == a.email.lower()))
        if user is None:
            user = User(email=a.email.lower(), name=a.name, password_hash=hash_password(password))
            s.add(user)
        else:
            user.password_hash = hash_password(password)
        user.role = "admin"
        user.is_active = True
        s.commit()
    print(f"Admin account ready: {a.email.lower()}")
    return 0


def _seed_demo(a: argparse.Namespace) -> int:
    """Create demo templates (genuine reference copies) and sample files to try."""
    import random

    import cv2
    from sqlalchemy import select

    from docauth import synth
    from docauth.config import get_settings
    from docauth.db import Database
    from docauth.models import Template

    settings = get_settings()
    settings.ensure_dirs()
    db = Database(settings.db_url)
    db.create_all()
    out = Path(a.out) if a.out else settings.data_dir / "samples"
    out.mkdir(parents=True, exist_ok=True)
    created = 0
    with db.session() as s:
        for k, layout in enumerate((11, 23, 37)):
            ref = synth.render_document(seed=layout * 7, layout_seed=layout)
            name = f"{ref.doc_type.title()} - {ref.issuer} (demo)"
            if s.scalar(select(Template).where(Template.name == name)) is None:
                fname = f"demo_{layout}.png"
                cv2.imwrite(str(settings.templates_dir / fname), ref.image)
                s.add(
                    Template(
                        name=name,
                        doc_type=ref.doc_type.title(),
                        description="Synthetic reference copy created by seed-demo.",
                        image_file=fname,
                        width=ref.image.shape[1],
                        height=ref.image.shape[0],
                        ignore_regions=ref.variable_regions(),
                    )
                )
                created += 1
            rng = random.Random(layout)
            # a genuine copy of the same certificate type (different person), scanned
            genuine = synth.render_document(seed=layout * 7 + 1, layout_seed=layout)
            g = synth.jpeg(synth.scan_effects(genuine.image, rng), 88)
            (out / f"{k + 1}_genuine_{genuine.doc_type.lower().replace(' ', '_')}.jpg").write_bytes(
                synth.jpeg_bytes(g, 90)
            )
            for kind in ("text_replace", "splice"):
                t, _, _ = synth.tamper(g, genuine, rng, kind)
                (out / f"{k + 1}_forged_{kind}.jpg").write_bytes(synth.jpeg_bytes(t, 90))
        s.commit()
    nat = synth.natural_image(42)
    cm = nat.copy()
    cm[400:540, 620:800] = nat[120:260, 140:320]
    (out / "photo_copy_move.jpg").write_bytes(synth.jpeg_bytes(cm, 92))
    print(f"Created {created} demo template(s); sample files in {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="docauth", description="DocAuth forgery detection")
    sub = p.add_subparsers(dest="cmd", required=True)

    an = sub.add_parser("analyze", help="analyse a document from the command line")
    an.add_argument("file")
    an.add_argument("--template", help="reference image/PDF of a genuine document")
    an.add_argument("--ignore", help="JSON file with normalised ignore regions for the template")
    an.add_argument("--out", help="directory for page images and forensic maps")
    an.add_argument("--json", action="store_true", help="print the full JSON report")
    an.set_defaults(fn=_analyze)

    sv = sub.add_parser("serve", help="run the web server")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(fn=_serve)

    ca = sub.add_parser("create-admin", help="create or promote an admin account")
    ca.add_argument("--email", required=True)
    ca.add_argument("--name", default="Administrator")
    ca.add_argument("--password", help="omit to be prompted")
    ca.set_defaults(fn=_create_admin)

    sd = sub.add_parser("seed-demo", help="add demo templates and sample documents")
    sd.add_argument("--out", help="where to write sample files (default data/samples)")
    sd.set_defaults(fn=_seed_demo)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
