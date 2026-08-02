from fastapi.testclient import TestClient

from tracefold.api import app


def test_health_and_version() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service_version": "0.1.0"}
    assert client.get("/version").status_code == 200


def test_compress_is_runnable() -> None:
    request = {
        "source_text": "Boilerplate. Boilerplate. timeout = 30 seconds.",
        "source_kind": "document",
        "tokenizer_backend": "fixture-only",
        "tokenizer_encoding": "utf8-byte",
    }
    client = TestClient(app)
    assert client.post("/v1/compress", json={}).status_code == 422
    response = client.post("/v1/compress", json=request)
    assert response.status_code == 200
    assert response.json()["status"] == "incompressible"
    assert response.json()["tokenizer_identity"]["implementation"] == "fixture-only"
    request["tokenizer_backend"] = "missing"
    assert client.post("/v1/compress", json=request).status_code == 422
