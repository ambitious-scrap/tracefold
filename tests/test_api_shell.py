from fastapi.testclient import TestClient

from tracefold.api import app


def test_health_and_version() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service_version": "0.1.0"}
    assert client.get("/version").status_code == 200


def test_compress_is_explicitly_unimplemented() -> None:
    request = {
        "sources": [
            {
                "input_ordinal": 0,
                "kind": "text",
                "authority": "user",
                "media_type": "text/plain",
                "text": "fixture",
                "bytes_base64": None,
                "file_path": None,
                "message_id": None,
                "role": None,
            }
        ],
        "query": None,
        "target_reduction": None,
        "target_token_budget": 40,
        "mode": "safe",
        "content_type": "text/plain",
        "target_tokenizer": {
            "implementation": "fixture",
            "identifier": "fixture",
            "revision": "1",
            "configuration_hash": "sha256:" + "a" * 64,
        },
        "return_provenance": True,
        "return_certificate": True,
    }
    client = TestClient(app)
    assert client.post("/v1/compress", json={}).status_code == 422
    response = client.post("/v1/compress", json=request)
    assert response.status_code == 501
    assert response.json()["code"] == "PHASE_1_NOT_IMPLEMENTED"
