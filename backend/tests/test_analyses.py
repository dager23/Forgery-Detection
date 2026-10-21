import io

from conftest import bearer, register, wait_done


def _upload(client, data, token, name="doc.jpg", **form):
    files = {"file": (name, io.BytesIO(data), "application/octet-stream")}
    return client.post("/api/analyses", files=files, data=form, headers=bearer(token))


def test_full_analysis_flow(client, user_token, genuine_jpeg):
    r = _upload(client, genuine_jpeg, user_token, "certificate.jpg")
    assert r.status_code == 202, r.text
    created = r.json()
    assert created["status"] in ("queued", "running")
    body = wait_done(client, created["id"], bearer(user_token))
    assert body["status"] == "done", body.get("error")
    assert body["verdict"] in ("authentic", "suspicious", "tampered")
    assert 0 <= body["score"] <= 100
    result = body["result"]
    keys = {m["key"] for m in result["modules"]}
    assert {
        "metadata",
        "ela",
        "noise",
        "jpeg",
        "copymove",
        "template",
        "cnn",
        "segmentation",
    } <= keys
    # every artifact referenced in the result is downloadable
    page = result["pages"][0]
    assert (
        client.get(
            f"/api/analyses/{created['id']}/files/{page['image']}", headers=bearer(user_token)
        ).status_code
        == 200
    )
    for m in result["modules"]:
        for a in m["artifacts"]:
            r = client.get(
                f"/api/analyses/{created['id']}/files/{a['file']}", headers=bearer(user_token)
            )
            assert r.status_code == 200, a
    # PDF report
    r = client.get(f"/api/analyses/{created['id']}/report.pdf", headers=bearer(user_token))
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    # original download
    r = client.get(f"/api/analyses/{created['id']}/original", headers=bearer(user_token))
    assert r.status_code == 200 and r.content == genuine_jpeg


def test_isolation_between_users(client, user_token, natural_jpeg):
    aid = _upload(client, natural_jpeg, user_token).json()["id"]
    other = register(client, "eve@example.com")["access_token"]
    client.cookies.clear()
    assert client.get(f"/api/analyses/{aid}", headers=bearer(other)).status_code == 404
    assert client.delete(f"/api/analyses/{aid}", headers=bearer(other)).status_code == 404
    assert client.get("/api/analyses", headers=bearer(other)).json()["total"] == 0
    assert client.get("/api/analyses?scope=all", headers=bearer(other)).status_code == 403
    wait_done(client, aid, bearer(user_token))


def test_admin_sees_all(client, user_token, admin_token, natural_jpeg):
    aid = _upload(client, natural_jpeg, user_token).json()["id"]
    wait_done(client, aid, bearer(user_token))
    assert client.get(f"/api/analyses/{aid}", headers=bearer(admin_token)).status_code == 200
    page = client.get("/api/analyses?scope=all", headers=bearer(admin_token)).json()
    assert any(i["id"] == aid for i in page["items"])


def test_rejects_bad_uploads(client, user_token):
    r = _upload(client, b"MZ\x90\x00 definitely not an image", user_token, "evil.jpg")
    assert r.status_code == 415
    r = _upload(client, b"", user_token)
    assert r.status_code == 400
    big = b"\xff\xd8\xff" + b"0" * (6 * 1024 * 1024)
    assert _upload(client, big, user_token).status_code == 413
    r = _upload(client, b"\xff\xd8\xff\xe0", user_token, template_id="999")
    assert r.status_code == 400


def test_corrupt_image_fails_gracefully(client, user_token):
    r = _upload(client, b"\xff\xd8\xff\xe0" + b"\x00" * 200, user_token)
    assert r.status_code == 202
    body = wait_done(client, r.json()["id"], bearer(user_token))
    assert body["status"] == "failed"
    assert "decode" in body["error"].lower()


def test_list_filter_stats_delete_rerun(client, user_token, natural_jpeg):
    ids = [_upload(client, natural_jpeg, user_token, f"img{i}.jpg").json()["id"] for i in range(2)]
    for i in ids:
        wait_done(client, i, bearer(user_token))
    page = client.get("/api/analyses?q=img1", headers=bearer(user_token)).json()
    assert page["total"] == 1 and page["items"][0]["filename"] == "img1.jpg"
    stats = client.get("/api/analyses/stats", headers=bearer(user_token)).json()
    assert stats["total"] == 2 and stats["pending"] == 0
    r = client.post(f"/api/analyses/{ids[0]}/rerun", headers=bearer(user_token))
    assert r.status_code == 202
    assert wait_done(client, ids[0], bearer(user_token))["status"] == "done"
    assert client.delete(f"/api/analyses/{ids[1]}", headers=bearer(user_token)).status_code == 204
    assert client.get(f"/api/analyses/{ids[1]}", headers=bearer(user_token)).status_code == 404


def test_artifact_path_traversal_blocked(client, user_token, natural_jpeg):
    aid = _upload(client, natural_jpeg, user_token).json()["id"]
    wait_done(client, aid, bearer(user_token))
    for name in ("..%2F..%2Fdocauth.db", "../secret", "page_0.jpg.exe", "PAGE_0.JPG"):
        r = client.get(f"/api/analyses/{aid}/files/{name}", headers=bearer(user_token))
        assert r.status_code == 404, name
