import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from main import app
from app.api.static import get_current_user


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    # Setup a dummy generated image file
    static_gen_dir = Path(__file__).resolve().parent.parent.parent / "static" / "generated_images"
    static_gen_dir.mkdir(parents=True, exist_ok=True)
    test_img = static_gen_dir / "20260822_105426_test_dummy.png"
    test_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    try:
        app.dependency_overrides[get_current_user] = lambda: "usr_test123"
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        if test_img.exists():
            test_img.unlink()


def test_unauthenticated_static_image_returns_401():
    client = TestClient(app)
    response = client.get("/v1/static/generated_images/20260822_105426_test_dummy.png")
    assert response.status_code == 401
    assert response.headers.get("content-type") == "application/problem+json"


def test_authenticated_static_image_serves_file_and_content_type(auth_client):
    response = auth_client.get("/v1/static/generated_images/20260822_105426_test_dummy.png")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "image/png"
    assert len(response.content) > 0


def test_authenticated_static_image_traversal_returns_404(auth_client):
    response = auth_client.get("/v1/static/generated_images/../secret.png")
    assert response.status_code == 404
