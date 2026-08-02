from __future__ import annotations

import json

import httpx
import pytest

from tracefold.benchmark import _manifest, _request_for, deterministic_run_id, prepare_contexts
from tracefold.phase7_fixtures import build_context_proof_bench
from tracefold.schemas.phase7 import (
    BenchmarkRunMode,
    TargetMode,
    TargetRequest,
    TargetSettings,
    TargetStatus,
)
from tracefold.target import TargetAdapter, build_target_request
from tracefold.tokenizers import TiktokenTokenizer


def _settings(mode: TargetMode, *, delay: float = 0) -> TargetSettings:
    return TargetSettings(
        mode=mode,
        model_id="gemini-test",
        endpoint_class="openai_compatible",
        request_timeout_seconds=1,
        temperature=0,
        maximum_output_tokens=16,
        seed=0,
        maximum_retries=2,
        inter_request_delay_seconds=delay,
    )


def _request(label: str) -> TargetRequest:
    return build_target_request(
        request_id=deterministic_run_id(label),
        benchmark_item_id=label,
        method_id="full_context",
        model_id="gemini-test",
        system_prompt="system",
        user_prompt="user",
        context="context",
        temperature=0,
        maximum_output_tokens=16,
        seed=0,
        timeout_seconds=1,
    )


def test_live_pacing_occurs_only_between_requests() -> None:
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gemini-test",
                "choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}],
            },
            request=request,
        )

    adapter = TargetAdapter(
        _settings(TargetMode.LIVE, delay=7),
        api_base_url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        allow_live=True,
    )
    assert adapter.invoke(_request("first")).status == TargetStatus.SUCCESS
    assert sleeps == []
    assert adapter.invoke(_request("second")).status == TargetStatus.SUCCESS
    assert sleeps == [7]


def test_disabled_and_replay_modes_never_sleep() -> None:
    sleeps: list[float] = []
    disabled = TargetAdapter(_settings(TargetMode.DISABLED, delay=7), sleep=sleeps.append)
    assert disabled.invoke(_request("disabled")).status == TargetStatus.UNAVAILABLE
    replay = TargetAdapter(_settings(TargetMode.REPLAY, delay=7), sleep=sleeps.append)
    assert replay.invoke(_request("replay")).error_code == "REPLAY_MISSING"
    assert sleeps == []


def test_retry_after_is_respected_and_provider_secret_is_sanitized() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "5"}, request=request)
        return httpx.Response(
            400,
            json=[
                {
                    "error": {
                        "code": "bad_request",
                        "message": "Authorization: Bearer test-secret rejected",
                    }
                }
            ],
            request=request,
        )

    response = TargetAdapter(
        _settings(TargetMode.LIVE),
        api_base_url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        allow_live=True,
    ).invoke(_request("retry"))
    assert sleeps == [5]
    assert response.retry_count == 1
    assert "test-secret" not in (response.error_message or "")
    assert response.error_message == "Authorization: Bearer [redacted] rejected"


def test_gemini_seed_capability_omits_seed_for_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TRACEFOLD_API_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    )
    monkeypatch.setenv("TRACEFOLD_API_KEY", "test-secret")
    monkeypatch.setenv("TRACEFOLD_TARGET_MODEL", "gemini-test")
    monkeypatch.setenv("TRACEFOLD_TARGET_SUPPORTS_SEED", "0")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "seed" not in json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "gemini-test",
                "choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}],
            },
            request=request,
        )

    adapter = TargetAdapter.from_environment(
        mode=TargetMode.LIVE,
        transport=httpx.MockTransport(handler),
        allow_live=True,
    )
    item = build_context_proof_bench()[0]
    prepared = prepare_contexts(
        (item,),
        tokenizer=TiktokenTokenizer("cl100k_base"),
        method_ids=("full_context",),
        compiler_commit="compiler-test",
        benchmark_runner_commit="runner-test",
    )[0]
    request = _request_for(item, prepared, adapter.settings)
    assert adapter.settings.seed_supported is False
    assert request.seed is None
    assert adapter.invoke(request).status == TargetStatus.SUCCESS


def test_manifest_records_inter_request_delay() -> None:
    manifest = _manifest(
        mode=BenchmarkRunMode.SMOKE_LIVE,
        item_count=5,
        method_ids=("full_context", "cprgc_target"),
        model_id="gemini-test",
        tokenizer=TiktokenTokenizer("cl100k_base"),
        inter_request_delay_seconds=7,
        random_seed=None,
        target_seed_supported=False,
    )
    assert manifest.inter_request_delay_seconds == 7
    assert manifest.random_seed is None
    assert manifest.target_seed_supported is False
