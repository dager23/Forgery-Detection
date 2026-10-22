from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docauth import synth
from docauth.app import create_app
from docauth.config import Settings

# identical synthetic documents on Windows, Linux and macOS (system fonts differ)
os.environ.setdefault("DOCAUTH_SYNTH_FONTS", "builtin")

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "admin-pass-123"  # test-only credential


@pytest.fixture(autouse=True)
def _no_models(tmp_path_factory, monkeypatch):
    """Run without trained weights/calibration so tests are fast and deterministic."""
    empty = tmp_path_factory.mktemp("weights")
    monkeypatch.setenv("DOCAUTH_WEIGHTS_DIR", str(empty))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        secret_key="test-secret-key-" + "x" * 32,
        admin_email=ADMIN_EMAIL,
        admin_password=ADMIN_PASSWORD,
        frontend_dist=tmp_path / "no-frontend",
        analysis_workers=2,
        max_upload_mb=5,
        _env_file=None,
    )


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def register(client: TestClient, email: str, name: str = "Tester", password: str = "s3cret-pass"):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_token(client: TestClient) -> str:
    tok = register(client, "user@example.com")["access_token"]
    client.cookies.clear()
    return tok


@pytest.fixture
def admin_token(client: TestClient) -> str:
    r = client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return r.json()["access_token"]


def wait_done(client: TestClient, analysis_id: str, headers: dict, timeout: float = 90) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/analyses/{analysis_id}", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.2)
    raise AssertionError("analysis did not finish in time")


@pytest.fixture(scope="session")
def genuine_jpeg() -> bytes:
    data, _, _ = synth.make_sample(4242, tampered=False)
    return data


@pytest.fixture(scope="session")
def natural_jpeg() -> bytes:
    return synth.jpeg_bytes(synth.natural_image(7, (480, 640)), 92)
