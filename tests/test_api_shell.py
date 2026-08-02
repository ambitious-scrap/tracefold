import json
from pathlib import Path

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


def test_public_tiktoken_mapping_and_validation() -> None:
    client = TestClient(app)
    request = {
        "source_text": "Routine notes. Routine notes. The timeout is 5000 ms for gateway-api.",
        "source_kind": "document",
        "media_type": "text/plain",
        "mode": "target",
        "tokenizer_backend": "tiktoken",
        "tokenizer_encoding": "cl100k_base",
        "maximum_recovery_attempts": 3,
    }
    response = client.post("/v1/compress", json=request)
    assert response.status_code == 200
    payload = response.json()
    assert payload["tokenizer_identity"]["implementation"] == "tiktoken"
    assert payload["tokenizer_identity"]["identifier"] == "cl100k_base"
    assert not {"api_key", "provider", "target_model"}.intersection(payload)
    assert (
        client.post("/v1/compress", json={**request, "target_token_budget": 0}).status_code == 422
    )


def test_python_protected_floor_is_incompressible() -> None:
    item_path = Path("reports/runs/phase9-gemini-primary/benchmark-items.jsonl")
    item = next(
        value
        for value in (
            json.loads(line) for line in item_path.read_text(encoding="utf-8").splitlines()
        )
        if value["item_id"] == "cpb-python-01"
    )
    response = TestClient(app).post(
        "/v1/compress",
        json={
            "source_text": item["context"],
            "source_kind": "python",
            "media_type": "text/x-python",
            "mode": "target",
            "query": item["question"],
            "tokenizer_backend": "tiktoken",
            "tokenizer_encoding": "cl100k_base",
            "maximum_recovery_attempts": 3,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "incompressible"
    assert payload["final_reduction"] is None
    assert payload["compressed_context"] == item["context"]
