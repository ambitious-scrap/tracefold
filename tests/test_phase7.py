from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import httpx
import pytest

from tracefold.benchmark import (
    DEFAULT_METHOD_IDS,
    deterministic_run_id,
    prepare_artifacts,
    prepare_contexts,
    score_answer,
    summarize_scores,
)
from tracefold.cli import _selected_prepared
from tracefold.phase7_fixtures import (
    build_context_proof_bench,
    build_controlled_context_stress,
)
from tracefold.schemas.phase7 import (
    BenchmarkRunMode,
    TargetMode,
    TargetRequest,
    TargetResponse,
    TargetSettings,
    TargetStatus,
)
from tracefold.target import (
    TargetAdapter,
    build_target_request,
    load_replay_records,
    replay_record_from_response,
    replay_record_hash,
)


def _settings(mode: TargetMode = TargetMode.DISABLED) -> TargetSettings:
    return TargetSettings(
        mode=mode,
        model_id="test-model",
        endpoint_class="test",
        request_timeout_seconds=1.0,
        temperature=0.0,
        maximum_output_tokens=16,
        seed=0,
        maximum_retries=2,
    )


def _request(method_id: str = "full_context") -> TargetRequest:
    return build_target_request(
        request_id=deterministic_run_id(f"phase7-test:{method_id}"),
        benchmark_item_id="cpb-document-01",
        method_id=method_id,
        model_id="test-model",
        system_prompt="system",
        user_prompt="user",
        context="context",
        temperature=0.0,
        maximum_output_tokens=16,
        seed=0,
        timeout_seconds=1.0,
    )


def test_target_modes_hashes_and_live_permission() -> None:
    request = _request()
    disabled = TargetAdapter(_settings()).invoke(request)
    assert disabled.status == TargetStatus.UNAVAILABLE
    assert disabled.error_code == "TARGET_DISABLED"

    tampered = request.model_copy(update={"request_hash": "sha256:" + "0" * 64})
    invalid = TargetAdapter(_settings()).invoke(tampered)
    assert invalid.error_code == "REQUEST_HASH_MISMATCH"

    live = TargetAdapter(
        _settings(TargetMode.LIVE),
        api_base_url="https://target.example",
        api_key="not-printed",
        allow_live=False,
    ).invoke(request)
    assert live.status == TargetStatus.INFRASTRUCTURE_FAILURE
    assert live.error_code == "LIVE_PERMISSION_REQUIRED"


def test_target_live_parses_usage_and_response_without_logging_secrets() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert req.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            json={
                "id": "provider-1",
                "model": "test-model",
                "choices": [{"message": {"content": "5000"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
            },
            request=req,
        )

    response = TargetAdapter(
        _settings(TargetMode.LIVE),
        api_base_url="https://target.example",
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
        allow_live=True,
    ).invoke(_request())
    assert calls == 1
    assert response.status == TargetStatus.SUCCESS
    assert response.answer_text == "5000"
    assert response.input_tokens == 5
    assert response.output_tokens == 1
    assert response.raw_response_hash is not None
    assert "test-secret" not in (response.error_message or "")


def test_target_retries_transient_failures_only() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, json={"error": {"code": "busy"}}, request=req)
        return httpx.Response(
            200,
            json={
                "id": "provider-2",
                "model": "test-model",
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            },
            request=req,
        )

    response = TargetAdapter(
        _settings(TargetMode.LIVE),
        api_base_url="https://target.example",
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        allow_live=True,
    ).invoke(_request("head_tail"))
    assert response.status == TargetStatus.SUCCESS
    assert response.retry_count == 2
    assert calls == 3
    assert sleeps == [0.25, 0.5]


def test_target_malformed_and_auth_errors_are_infrastructure_failures() -> None:
    def malformed(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []}, request=req)

    malformed_response = TargetAdapter(
        _settings(TargetMode.LIVE),
        api_base_url="https://target.example",
        api_key="test-secret",
        transport=httpx.MockTransport(malformed),
        allow_live=True,
    ).invoke(_request())
    assert malformed_response.status == TargetStatus.INFRASTRUCTURE_FAILURE
    assert malformed_response.error_code == "EMPTY_PROVIDER_RESPONSE"

    def unauthorized(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "invalid_api_key", "message": "bad key"}},
            request=req,
        )

    auth_response = TargetAdapter(
        _settings(TargetMode.LIVE),
        api_base_url="https://target.example",
        api_key="test-secret",
        transport=httpx.MockTransport(unauthorized),
        allow_live=True,
    ).invoke(_request())
    assert auth_response.error_code == "invalid_api_key"
    assert auth_response.retry_count == 0
    assert "test-secret" not in (auth_response.error_message or "")


def test_replay_hashes_and_model_validation() -> None:
    response = TargetResponse(
        request_id=_request().request_id,
        model_id="test-model",
        answer_text="5000",
        input_tokens=4,
        output_tokens=1,
        status=TargetStatus.SUCCESS,
    )
    request = _request()
    record = replay_record_from_response(request, response)
    replayed = TargetAdapter(_settings(TargetMode.REPLAY), replay_records=[record]).invoke(request)
    assert replayed.status == TargetStatus.SUCCESS
    assert replayed.answer_text == "5000"
    assert replayed.replay_record_hash == record.replay_record_hash

    bad_record = record.model_copy(update={"replay_record_hash": "sha256:" + "0" * 64})
    bad = TargetAdapter(_settings(TargetMode.REPLAY), replay_records=[bad_record]).invoke(request)
    assert bad.error_code == "REPLAY_HASH_MISMATCH"

    bad_response_draft = record.model_copy(update={"response_hash": "sha256:" + "0" * 64})
    bad_response = bad_response_draft.model_copy(
        update={"replay_record_hash": replay_record_hash(bad_response_draft)}
    )
    bad = TargetAdapter(_settings(TargetMode.REPLAY), replay_records=[bad_response]).invoke(request)
    assert bad.error_code == "RESPONSE_HASH_MISMATCH"

    wrong_model = TargetAdapter(
        _settings(TargetMode.REPLAY),
        replay_records=[record.model_copy(update={"model_id": "other"})],
    ).invoke(request)
    assert wrong_model.error_code == "REPLAY_MODEL_MISMATCH"


def test_replay_file_rejects_duplicate_request_hash(tmp_path: Path) -> None:
    request = _request()
    response = TargetResponse(
        request_id=request.request_id,
        model_id="test-model",
        answer_text="ok",
        status=TargetStatus.SUCCESS,
    )
    record = replay_record_from_response(request, response)
    path = tmp_path / "replay.jsonl"
    line = json.dumps(record.model_dump(mode="json"))
    path.write_text(line + "\n" + line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate replay request hash"):
        load_replay_records(path)


def test_context_proof_bench_is_balanced_and_deterministic() -> None:
    first = build_context_proof_bench()
    second = build_context_proof_bench()
    assert [item.model_dump(mode="json") for item in first] == [
        item.model_dump(mode="json") for item in second
    ]
    assert len(first) == 50
    assert Counter(item.source_kind.value for item in first) == {
        "document": 10,
        "dialogue": 10,
        "json": 10,
        "log": 10,
        "python": 10,
    }
    assert len(build_controlled_context_stress()) >= 8


def test_prepared_methods_use_matched_budgets_and_item_filter() -> None:
    items = build_context_proof_bench()[:1]
    prepared = prepare_contexts(items, method_ids=DEFAULT_METHOD_IDS)
    assert {item.matched_budget for item in prepared} == {prepared[0].matched_budget}
    selected = _selected_prepared(
        list(prepared),
        ("full_context", "cprgc_target"),
        {items[0].item_id},
    )
    assert {item.method_id for item in selected} == {"full_context", "cprgc_target"}
    assert all(item.item_id == items[0].item_id for item in selected)


def test_prepare_artifacts_and_report_are_structurally_unmeasured_without_responses(
    tmp_path: Path,
) -> None:
    result = prepare_artifacts(tmp_path, method_ids=("full_context", "cprgc_target"))
    assert result["summary"].mode == BenchmarkRunMode.PREPARE
    assert result["summary"].primary_gate == "unmeasured"
    assert result["summary"].live_request_count == 0
    assert (tmp_path / "controlled-context-stress.jsonl").exists()
    assert (tmp_path / "pricing-config.example.json").exists()
    assert not (tmp_path / "responses-sanitized.jsonl").exists()


def test_score_types_and_paired_metrics() -> None:
    items = build_context_proof_bench()
    for item in items:
        answer = item.answer_key.accepted_answers[0]
        if item.answer_key.required_units:
            answer = f"{answer} {' '.join(item.answer_key.required_units)}"
        response = TargetResponse(
            request_id=deterministic_run_id(item.item_id),
            model_id="test-model",
            answer_text=answer,
            status=TargetStatus.SUCCESS,
        )
        correct, score, infrastructure = score_answer(item, response)
        assert correct, item.item_id
        assert score == 1.0, item.item_id
        assert not infrastructure

    assert summarize_scores([]) == {
        "methods": {},
        "paired_disagreements": {},
        "record_count": 0,
    }


def test_replay_record_hash_changes_when_record_changes() -> None:
    request = _request()
    response = TargetResponse(
        request_id=request.request_id,
        model_id="test-model",
        answer_text="ok",
        status=TargetStatus.SUCCESS,
    )
    record = replay_record_from_response(request, response)
    changed = record.model_copy(update={"answer_text": "changed"})
    assert replay_record_hash(record) != replay_record_hash(changed)
