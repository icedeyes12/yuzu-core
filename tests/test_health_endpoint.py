from fastapi.testclient import TestClient

from main import app


def test_health_endpoint_is_public_and_returns_ok() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# No lifespan context: this endpoint must not require startup dependencies.
TestClient(app).close()
