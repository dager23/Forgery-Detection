import io
import json
import random

import cv2
from conftest import bearer, wait_done

from docauth import synth


def _png(img) -> bytes:
    return cv2.imencode(".png", img)[1].tobytes()


def _create_template(client, admin_token, layout=5):
    ref = synth.render_document(seed=100, layout_seed=layout)
    r = client.post(
        "/api/templates",
        files={"file": ("ref.png", io.BytesIO(_png(ref.image)), "image/png")},
        data={
            "name": "Income certificate",
            "doc_type": "income",
            "ignore_regions": json.dumps(ref.variable_regions()),
        },
        headers=bearer(admin_token),
    )
    assert r.status_code == 201, r.text
    return r.json(), ref


def test_template_crud_and_permissions(client, admin_token, user_token):
    t, _ = _create_template(client, admin_token)
    assert t["width"] > 0 and len(t["ignore_regions"]) >= 6
    ref = synth.render_document(seed=1, layout_seed=1)
    r = client.post(
        "/api/templates",
        files={"file": ("x.png", io.BytesIO(_png(ref.image)), "image/png")},
        data={"name": "nope"},
        headers=bearer(user_token),
    )
    assert r.status_code == 403
    assert len(client.get("/api/templates", headers=bearer(user_token)).json()) == 1
    assert (
        client.get(f"/api/templates/{t['id']}/image", headers=bearer(user_token)).status_code == 200
    )
    r = client.patch(
        f"/api/templates/{t['id']}",
        json={"ignore_regions": [{"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.05}]},
        headers=bearer(admin_token),
    )
    assert r.status_code == 200 and len(r.json()["ignore_regions"]) == 1
    r = client.patch(
        f"/api/templates/{t['id']}",
        json={"ignore_regions": [{"x": 2, "y": 0, "w": 1, "h": 1}]},
        headers=bearer(admin_token),
    )
    assert r.status_code == 422
    assert (
        client.delete(f"/api/templates/{t['id']}", headers=bearer(admin_token)).status_code == 204
    )


def test_template_matching_genuine_vs_forged(client, admin_token, user_token):
    t, ref = _create_template(client, admin_token)
    rng = random.Random(3)
    genuine = synth.render_document(seed=200, layout_seed=5)  # same template, different person
    scanned = synth.jpeg(synth.scan_effects(genuine.image, rng, 0.7), 90)

    forged = scanned.copy()
    # forge fixed text: paint over the body paragraph and the seal (not variable fields)
    x, y, w, h = genuine.seal_box
    forged[y : y + h, x : x + w] = 245
    cv2.putText(
        forged, "APPROVED", (x - 40, y + h // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (20, 20, 20), 3
    )

    results = {}
    for name, img in (("genuine", scanned), ("forged", forged)):
        data = synth.jpeg_bytes(img, 92)
        r = client.post(
            "/api/analyses",
            files={"file": (f"{name}.jpg", io.BytesIO(data), "image/jpeg")},
            data={"template_id": str(t["id"])},
            headers=bearer(user_token),
        )
        assert r.status_code == 202
        body = wait_done(client, r.json()["id"], bearer(user_token))
        assert body["status"] == "done"
        assert body["template_name"] == "Income certificate"
        results[name] = next(m for m in body["result"]["modules"] if m["key"] == "template")

    assert results["genuine"]["status"] == "ok"
    assert len(results["genuine"]["boxes"]) == 0, results["genuine"]["boxes"]
    assert results["forged"]["suspicion"] > 0.6
    assert len(results["forged"]["boxes"]) >= 1
    sx, sy, sw, sh = genuine.seal_box
    assert any(
        b["x"] < sx + sw and sx < b["x"] + b["w"] and b["y"] < sy + sh and sy < b["y"] + b["h"]
        for b in results["forged"]["boxes"]
    )


def test_auto_template_detection(client, admin_token, user_token):
    _create_template(client, admin_token, layout=9)
    genuine = synth.render_document(seed=300, layout_seed=9)
    data = synth.jpeg_bytes(genuine.image, 92)
    r = client.post(
        "/api/analyses",
        files={"file": ("a.jpg", io.BytesIO(data), "image/jpeg")},
        headers=bearer(user_token),
    )
    body = wait_done(client, r.json()["id"], bearer(user_token))
    tm = next(m for m in body["result"]["modules"] if m["key"] == "template")
    assert tm["status"] == "ok"
    assert body["result"]["template"]["auto_selected"] is True
