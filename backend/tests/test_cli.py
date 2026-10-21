import json

from docauth import synth
from docauth.cli import main


def test_cli_analyze_text_and_json(tmp_path, capsys):
    f = tmp_path / "photo.jpg"
    f.write_bytes(synth.jpeg_bytes(synth.natural_image(4, (320, 480)), 90))
    assert main(["analyze", str(f)]) == 0
    out = capsys.readouterr().out
    assert "photo.jpg:" in out and "Copy-move detection" in out

    assert main(["analyze", str(f), "--json", "--out", str(tmp_path / "art")]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] in ("authentic", "suspicious", "tampered")
    assert (tmp_path / "art" / "page_0.jpg").exists()
