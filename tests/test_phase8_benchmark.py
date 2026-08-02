from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tracefold.benchmark import (
    DEFAULT_METHOD_IDS,
    _request_for,
    coverage_ratio,
    filter_items_by_id_file,
    prepare_artifacts,
    prepare_contexts,
    provider_request_input_reduction,
)
from tracefold.phase7_fixtures import build_context_proof_bench
from tracefold.phase7_report import _gate
from tracefold.schemas.common import TokenizerIdentity
from tracefold.schemas.phase7 import (
    BenchmarkMetricSource,
    PreparedContext,
    TargetMode,
    TargetResponse,
    TargetSettings,
    TargetStatus,
)
from tracefold.serialization import canonical_json_bytes
from tracefold.target import TargetAdapter, replay_record_from_response, replay_record_hash
from tracefold.tokenizers import FixtureByteTokenizer, TiktokenTokenizer


def _settings() -> TargetSettings:
    return TargetSettings(
        mode=TargetMode.REPLAY,
        model_id="test-model",
        endpoint_class="test",
        request_timeout_seconds=1.0,
        temperature=0.0,
        maximum_output_tokens=16,
        seed=0,
        maximum_retries=0,
    )


@pytest.fixture(scope="module")
def configured_prepared() -> tuple[PreparedContext, ...]:
    tokenizer = TiktokenTokenizer("cl100k_base")
    return prepare_contexts(
        build_context_proof_bench()[:1],
        tokenizer=tokenizer,
        method_ids=DEFAULT_METHOD_IDS,
        compiler_commit="compiler-test",
        benchmark_runner_commit="runner-test",
    )


def test_prepare_requires_explicit_tokenizer() -> None:
    assert (
        inspect.signature(prepare_contexts).parameters["tokenizer"].default
        is inspect.Parameter.empty
    )
    assert (
        inspect.signature(prepare_artifacts).parameters["tokenizer"].default
        is inspect.Parameter.empty
    )


def test_one_configured_tokenizer_drives_every_method_and_budget(
    configured_prepared: tuple[PreparedContext, ...],
) -> None:
    rows = list(configured_prepared)
    target = next(item for item in rows if item.method_id == "cprgc_target")
    for item in rows:
        assert item.tokenizer_identity == target.tokenizer_identity
        assert item.tokenizer_identity is not None
        assert item.tokenizer_identity.identifier == "cl100k_base"
        assert item.metric_source == BenchmarkMetricSource.CONFIGURED_TOKENIZER
        assert item.original_token_count == item.original_configured_token_count
        assert item.context_token_count == item.context_configured_token_count
        assert item.matched_budget == item.matched_configured_token_budget
        if item.method_id not in {"full_context", "cprgc_aggressive"}:
            assert item.matched_budget == target.matched_budget
            assert item.context_token_count <= item.matched_budget
    assert target.hard_obligation_coverage == "1.000000"
    assert target.verified_mandatory_count == target.mandatory_obligation_count


def test_coverage_is_direct_and_zero_is_not_applicable() -> None:
    assert coverage_ratio(10, 10) == ("1.000000", "applicable")
    assert coverage_ratio(9, 10) == ("0.900000", "applicable")
    assert coverage_ratio(0, 0) == (None, "not_applicable")


def test_incomplete_coverage_cannot_pass_claim_gate(
    configured_prepared: tuple[PreparedContext, ...],
) -> None:
    target = next(item for item in configured_prepared if item.method_id == "cprgc_target")
    prepared = [target.model_copy(update={"item_id": f"item-{index}"}) for index in range(50)]
    prepared[0] = prepared[0].model_copy(update={"hard_obligation_coverage": "0.900000"})
    summary = {
        "methods": {
            "cprgc_target": {
                "denominator": 50,
                "paired_retention": 1.0,
                "mean_reduction": 0.75,
                "per_kind": {},
            }
        }
    }
    assert _gate(summary, prepared, []) == "fail"


def test_fixture_and_configured_metrics_remain_distinct() -> None:
    item = build_context_proof_bench()[:1]
    fixture = prepare_contexts(
        item,
        tokenizer=FixtureByteTokenizer(),
        method_ids=("full_context",),
        compiler_commit="compiler-test",
        benchmark_runner_commit="runner-test",
    )[0]
    configured = prepare_contexts(
        item,
        tokenizer=TiktokenTokenizer("cl100k_base"),
        method_ids=("full_context",),
        compiler_commit="compiler-test",
        benchmark_runner_commit="runner-test",
    )[0]
    assert fixture.metric_source == BenchmarkMetricSource.FIXTURE_BYTES
    assert configured.metric_source == BenchmarkMetricSource.CONFIGURED_TOKENIZER
    assert fixture.original_token_count != configured.original_token_count


def test_manifest_and_prepared_record_store_configured_tokenizer(tmp_path: Path) -> None:
    output = tmp_path / "run"
    result = prepare_artifacts(
        output,
        tokenizer=TiktokenTokenizer("cl100k_base"),
        items=build_context_proof_bench()[:1],
        method_ids=("full_context", "cprgc_target"),
    )
    manifest = canonical_json_bytes(
        __import__("json").loads((output / "run-manifest.json").read_text())
    )
    assert b"cl100k_base" in manifest
    assert b"configured_tokenizer" in manifest
    assert all(
        item.tokenizer_identity is not None and item.tokenizer_identity.identifier == "cl100k_base"
        for item in result["prepared"]
    )
    assert (output / "artifact-hashes.json").exists()
    with pytest.raises(FileExistsError):
        prepare_artifacts(
            output,
            tokenizer=TiktokenTokenizer("cl100k_base"),
            items=build_context_proof_bench()[:1],
            method_ids=("full_context",),
        )


def test_item_id_filter_is_ordered_and_rejects_mixed_input(tmp_path: Path) -> None:
    items = build_context_proof_bench()
    ids = tmp_path / "ids.txt"
    ids.write_text("cpb-python-01\ncpb-document-01\n", encoding="utf-8")
    selected = filter_items_by_id_file(items, ids)
    assert [item.item_id for item in selected] == ["cpb-document-01", "cpb-python-01"]
    ids.write_text("cpb-document-01\nunknown-item\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        filter_items_by_id_file(items, ids)


def test_committed_smoke_and_aggressive_selections_are_frozen_and_balanced() -> None:
    items = {item.item_id: item.source_kind.value for item in build_context_proof_bench()}
    smoke = Path("reports/runs/phase8-smoke-item-ids.txt").read_text().splitlines()
    aggressive = Path("reports/runs/phase8-aggressive-item-ids.txt").read_text().splitlines()
    assert len(smoke) == len(set(smoke)) == 5
    assert len(aggressive) == len(set(aggressive)) == 10
    assert sorted(items[item] for item in smoke) == [
        "dialogue",
        "document",
        "json",
        "log",
        "python",
    ]
    assert {
        kind: sum(items[item] == kind for item in aggressive) for kind in set(items.values())
    } == {
        "dialogue": 2,
        "document": 2,
        "json": 2,
        "log": 2,
        "python": 2,
    }


def test_provider_reduction_is_paired_and_missing_usage_is_null() -> None:
    assert provider_request_input_reduction(100, 25) == "0.750000"
    assert provider_request_input_reduction(None, 25) is None
    assert provider_request_input_reduction(100, None) is None


def test_replay_rejects_tokenizer_item_and_method_mismatch(
    configured_prepared: tuple[PreparedContext, ...],
) -> None:
    item = build_context_proof_bench()[0]
    prepared = next(value for value in configured_prepared if value.method_id == "full_context")
    request = _request_for(item, prepared, _settings())
    response = TargetResponse(
        request_id=request.request_id,
        model_id="test-model",
        answer_text="ok",
        input_tokens=10,
        output_tokens=1,
        status=TargetStatus.SUCCESS,
    )
    record = replay_record_from_response(request, response)
    fixture_identity = TokenizerIdentity.model_validate(
        FixtureByteTokenizer().identity.model_dump(mode="json")
    )
    wrong_tokenizer = record.model_copy(update={"tokenizer_identity": fixture_identity})
    wrong_tokenizer = wrong_tokenizer.model_copy(
        update={"replay_record_hash": replay_record_hash(wrong_tokenizer)}
    )
    replay = TargetAdapter(_settings(), replay_records=[wrong_tokenizer]).invoke(request)
    assert replay.error_code == "REPLAY_TOKENIZER_MISMATCH"

    wrong_item = record.model_copy(update={"benchmark_item_id": "cpb-document-02"})
    wrong_item = wrong_item.model_copy(
        update={"replay_record_hash": replay_record_hash(wrong_item)}
    )
    replay = TargetAdapter(_settings(), replay_records=[wrong_item]).invoke(request)
    assert replay.error_code == "REPLAY_ITEM_MISMATCH"

    wrong_method = record.model_copy(update={"method_id": "cprgc_target"})
    wrong_method = wrong_method.model_copy(
        update={"replay_record_hash": replay_record_hash(wrong_method)}
    )
    replay = TargetAdapter(_settings(), replay_records=[wrong_method]).invoke(request)
    assert replay.error_code == "REPLAY_METHOD_MISMATCH"
    assert b"api_key" not in canonical_json_bytes(record.model_dump(mode="json"))
    assert b"authorization" not in canonical_json_bytes(record.model_dump(mode="json"))
