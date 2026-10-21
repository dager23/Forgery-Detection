from conftest import ADMIN_EMAIL, bearer, register


def test_register_login_me_logout(client):
    body = register(client, "alice@example.com", "Alice")
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "user"
    # register sets an httpOnly session cookie that authenticates subsequent calls
    assert client.get("/api/auth/me").json()["name"] == "Alice"
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401

    r = client.post(
        "/api/auth/login", json={"email": "ALICE@example.com", "password": "s3cret-pass"}
    )
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_bearer_token_auth(client):
    token = register(client, "bob@example.com")["access_token"]
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=bearer(token)).status_code == 200
    assert client.get("/api/auth/me", headers=bearer(token + "x")).status_code == 401


def test_duplicate_email_rejected(client):
    register(client, "dup@example.com")
    r = client.post(
        "/api/auth/register",
        json={"name": "X", "email": "DUP@example.com", "password": "another-pass1"},
    )
    assert r.status_code == 409


def test_password_policy(client):
    for pw in ("short1", "allletterspassword", "12345678901"):
        r = client.post(
            "/api/auth/register", json={"name": "X", "email": "p@example.com", "password": pw}
        )
        assert r.status_code == 422, pw


def test_login_errors_do_not_leak_account_existence(client):
    register(client, "carol@example.com")
    client.cookies.clear()
    a = client.post(
        "/api/auth/login", json={"email": "carol@example.com", "password": "wrong-pass1"}
    )
    b = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass1"}
    )
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_login_throttling(client):
    register(client, "dave@example.com")
    client.cookies.clear()
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "dave@example.com", "password": "bad-pass-1"})
    r = client.post(
        "/api/auth/login", json={"email": "dave@example.com", "password": "s3cret-pass"}
    )
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_admin_bootstrap_and_user_management(client, admin_token, user_token):
    me = client.get("/api/auth/me", headers=bearer(admin_token)).json()
    assert me["email"] == ADMIN_EMAIL and me["role"] == "admin"
    assert client.get("/api/admin/users", headers=bearer(user_token)).status_code == 403
    users = client.get("/api/admin/users", headers=bearer(admin_token)).json()
    target = next(u for u in users if u["email"] == "user@example.com")
    r = client.patch(
        f"/api/admin/users/{target['id']}", json={"is_active": False}, headers=bearer(admin_token)
    )
    assert r.status_code == 200
    # deactivated users lose access immediately
    assert client.get("/api/auth/me", headers=bearer(user_token)).status_code == 401
    # admins cannot lock themselves out
    r = client.patch(
        f"/api/admin/users/{me['id']}", json={"role": "user"}, headers=bearer(admin_token)
    )
    assert r.status_code == 400


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    body = r.json()
    assert {m["key"] for m in body["modules"]} >= {"metadata", "ela", "template", "cnn"}
