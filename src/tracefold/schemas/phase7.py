"""Typed target-integration and benchmark records for Phase 7."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from tracefold.run_ids import validate_run_id
from tracefold.schemas.common import FinalAction, HashValue, StrictModel, TokenizerIdentity
from tracefold.schemas.phase2 import ContentType


class TargetMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"
    DISABLED = "disabled"


class TargetStatus(StrEnum):
    SUCCESS = "success"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"


class UsageSource(StrEnum):
    PROVIDER = "provider"
    PRODUCTION_TOKENIZER = "production_tokenizer"
    LOCAL_TOKENIZER = "local_tokenizer"
    UNKNOWN = "unknown"


class BenchmarkMetricSource(StrEnum):
    FIXTURE_BYTES = "fixture_bytes"
    CONFIGURED_TOKENIZER = "configured_tokenizer"
    PROVIDER_USAGE = "provider_usage"


class AnswerType(StrEnum):
    EXACT_STRING = "exact_string"
    IDENTIFIER = "identifier"
    NUMBER = "number"
    NUMBER_WITH_UNIT = "number_with_unit"
    DATE = "date"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    ORDERED_LIST = "ordered_list"
    SET = "set"
    JSON_FIELD = "json_field"
    CODE_SYMBOL = "code_symbol"
    SHORT_FREE_TEXT = "short_free_text"


class BenchmarkRunMode(StrEnum):
    PREPARE = "prepare"
    SMOKE_LIVE = "smoke-live"
    FULL_LIVE = "full-live"
    REPLAY = "replay"
    REPORT = "report"


class BenchmarkMethod(StrictModel):
    method_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    lossy: bool
    description: str = Field(min_length=1)


class UsageAccounting(StrictModel):
    source: UsageSource
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    tokenizer: TokenizerIdentity | None = None


class TargetSettings(StrictModel):
    mode: TargetMode
    model_id: str = Field(min_length=1)
    endpoint_class: str = Field(min_length=1)
    request_timeout_seconds: float = Field(gt=0)
    temperature: float = Field(ge=0, le=2)
    maximum_output_tokens: int = Field(gt=0)
    seed: int | None = None
    seed_supported: bool = True
    maximum_retries: int = Field(ge=0, le=2)
    inter_request_delay_seconds: float = Field(default=0, ge=0, le=120)


class TargetRequest(StrictModel):
    request_id: str = Field(min_length=1)
    benchmark_item_id: str = Field(min_length=1)
    method_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    context: str
    temperature: float = Field(ge=0, le=2)
    maximum_output_tokens: int = Field(gt=0)
    seed: int | None = None
    timeout_seconds: float = Field(gt=0)
    metadata: dict[str, str | int | bool] = Field(default_factory=dict)
    request_hash: HashValue

    @model_validator(mode="after")
    def valid_request_id(self) -> TargetRequest:
        validate_run_id(self.request_id)
        return self


class TargetResponse(StrictModel):
    request_id: str = Field(min_length=1)
    provider_request_id: str | None = None
    model_id: str = Field(min_length=1)
    answer_text: str | None = None
    finish_reason: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    request_latency_ms: float | None = Field(default=None, ge=0)
    time_to_first_token_ms: float | None = Field(default=None, ge=0)
    http_status: int | None = Field(default=None, ge=100, le=599)
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    raw_response_hash: HashValue | None = None
    replay_record_hash: HashValue | None = None
    status: TargetStatus

    @model_validator(mode="after")
    def successful_response_has_answer(self) -> TargetResponse:
        if self.status == TargetStatus.SUCCESS and self.answer_text is None:
            raise ValueError("successful target response requires answer_text")
        return self


class ReplayRecord(StrictModel):
    request_hash: HashValue
    model_id: str = Field(min_length=1)
    answer_text: str | None = None
    usage: UsageAccounting
    latency_ms: float | None = Field(default=None, ge=0)
    finish_reason: str | None = None
    sanitized_error_code: str | None = None
    sanitized_error_message: str | None = None
    response_hash: HashValue
    generated_at: datetime
    provider_request_id: str | None = None
    benchmark_item_id: str | None = None
    method_id: str | None = None
    prompt_hash: HashValue | None = None
    tokenizer_identity: TokenizerIdentity | None = None
    compiler_commit: str | None = None
    benchmark_runner_commit: str | None = None
    replay_record_hash: HashValue


class EvidenceSpan(StrictModel):
    span_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    label: str = Field(min_length=1)
    text_hash: HashValue

    @model_validator(mode="after")
    def valid_bounds(self) -> EvidenceSpan:
        if self.char_start > self.char_end:
            raise ValueError("evidence span bounds are reversed")
        return self


class AnswerKey(StrictModel):
    answer_type: AnswerType
    accepted_answers: list[str] = Field(min_length=1)
    exact_numeric_answer: str | None = None
    required_units: list[str] = Field(default_factory=list)
    required_identifiers: list[str] = Field(default_factory=list)
    json_path: str | None = None
    case_sensitive: bool = False

    @model_validator(mode="after")
    def numeric_key_is_explicit(self) -> AnswerKey:
        if self.answer_type in {AnswerType.NUMBER, AnswerType.NUMBER_WITH_UNIT}:
            if self.exact_numeric_answer is None:
                raise ValueError("numeric answer requires exact_numeric_answer")
        if self.answer_type == AnswerType.JSON_FIELD and self.json_path is None:
            raise ValueError("JSON answer requires json_path")
        return self


class BenchmarkItem(StrictModel):
    benchmark_version: str = "ContextProofBench-v1"
    item_id: str = Field(min_length=1)
    source_kind: ContentType
    source_id: str = Field(min_length=1)
    context: str
    question: str = Field(min_length=1)
    answer_key: AnswerKey
    supporting_spans: list[EvidenceSpan] = Field(min_length=1)
    protected_obligation_ids: list[str] = Field(default_factory=list)
    required_relation_ids: list[str] = Field(default_factory=list)
    difficulty: Literal["easy", "medium", "hard"]
    task_family: str = Field(min_length=1)
    query_hash: HashValue
    notes: str = ""

    @model_validator(mode="after")
    def spans_belong_to_item(self) -> BenchmarkItem:
        if any(span.source_id != self.source_id for span in self.supporting_spans):
            raise ValueError("supporting spans must belong to benchmark source")
        if any(span.char_end > len(self.context) for span in self.supporting_spans):
            raise ValueError("supporting span exceeds context")
        return self


class PreparedContext(StrictModel):
    item_id: str = Field(min_length=1)
    method_id: str = Field(min_length=1)
    context: str
    original_token_count: int = Field(ge=0)
    context_token_count: int = Field(ge=0)
    matched_budget: int = Field(ge=1)
    tokenizer_identity: TokenizerIdentity | None = None
    metric_source: BenchmarkMetricSource | None = None
    original_configured_token_count: int | None = Field(default=None, ge=0)
    context_configured_token_count: int | None = Field(default=None, ge=0)
    matched_configured_token_budget: int | None = Field(default=None, ge=1)
    configured_context_reduction: str | None = None
    compiler_commit: str | None = None
    benchmark_runner_commit: str | None = None
    requested_reduction: str | None = None
    raw_reduction: str | None = None
    final_reduction: str | None = None
    compression_status: str = Field(min_length=1)
    final_action: FinalAction
    certificate_hash: HashValue | None = None
    verification_status: str = Field(min_length=1)
    hard_obligation_coverage: str | None = None
    hard_obligation_coverage_status: Literal["applicable", "not_applicable"] = "not_applicable"
    relation_coverage: str | None = None
    relation_coverage_status: Literal["applicable", "not_applicable"] = "not_applicable"
    mandatory_obligation_count: int = Field(default=0, ge=0)
    verified_mandatory_count: int = Field(default=0, ge=0)
    discovered_relation_count: int = Field(default=0, ge=0)
    verified_relation_count: int = Field(default=0, ge=0)
    relation_class_diversity: int = Field(default=0, ge=0)
    exact_relation_count: int = Field(default=0, ge=0)
    inferred_relation_count: int = Field(default=0, ge=0)
    fallback: bool = False
    compiler_latency_ms: float | None = Field(default=None, ge=0)
    verification_latency_ms: float | None = Field(default=None, ge=0)
    recovery_latency_ms: float | None = Field(default=None, ge=0)
    total_local_pipeline_latency_ms: float | None = Field(default=None, ge=0)
    warnings: list[str] = Field(default_factory=list)


class ScoreRecord(StrictModel):
    item_id: str = Field(min_length=1)
    method_id: str = Field(min_length=1)
    source_kind: ContentType
    answer_type: AnswerType
    target_response: TargetResponse
    correct: bool
    score: float = Field(ge=0, le=1)
    full_context_correct: bool | None = None
    infrastructure_failure: bool = False
    original_token_count: int = Field(ge=0)
    context_token_count: int = Field(ge=0)
    input_reduction: str | None = None
    configured_context_reduction: str | None = None
    provider_request_input_reduction: str | None = None
    raw_reduction: str | None = None
    final_reduction: str | None = None
    target_latency_ms: float | None = Field(default=None, ge=0)
    local_compression_latency_ms: float | None = Field(default=None, ge=0)
    verification_latency_ms: float | None = Field(default=None, ge=0)
    recovery_latency_ms: float | None = Field(default=None, ge=0)
    end_to_end_latency_ms: float | None = Field(default=None, ge=0)
    input_cost: float | None = Field(default=None, ge=0)
    output_cost: float | None = Field(default=None, ge=0)
    total_cost: float | None = Field(default=None, ge=0)
    status: str = Field(min_length=1)


class PricingConfig(StrictModel):
    model_id: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    input_price_per_million_tokens: float | None = Field(default=None, ge=0)
    cached_input_price_per_million_tokens: float | None = Field(default=None, ge=0)
    output_price_per_million_tokens: float | None = Field(default=None, ge=0)
    reasoning_price_per_million_tokens: float | None = Field(default=None, ge=0)
    pricing_effective_date: str = Field(min_length=1)
    pricing_source_note: str = Field(min_length=1)


class BenchmarkRun(StrictModel):
    run_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    mode: BenchmarkRunMode
    model_id: str = Field(min_length=1)
    endpoint_class: str = Field(min_length=1)
    tokenizer_identity: TokenizerIdentity
    metric_source: BenchmarkMetricSource | None = None
    compiler_commit: str | None = None
    benchmark_runner_commit: str | None = None
    item_count: int = Field(ge=0)
    method_ids: list[str]
    request_count: int = Field(ge=0)
    run_timestamp: datetime
    pricing_config_hash: HashValue | None = None
    random_seed: int | None = None
    target_seed_supported: bool = True
    inter_request_delay_seconds: float = Field(default=0, ge=0, le=120)
    failures: list[str] = Field(default_factory=list)
    environment_summary: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_run(self) -> BenchmarkRun:
        validate_run_id(self.run_id)
        return self


class BenchmarkSummary(StrictModel):
    benchmark_version: str = Field(min_length=1)
    mode: BenchmarkRunMode
    item_count: int = Field(ge=0)
    method_count: int = Field(ge=0)
    expected_request_count: int = Field(ge=0)
    live_request_count: int = Field(ge=0)
    infrastructure_failure_count: int = Field(ge=0)
    structural_reduction_by_kind: dict[str, str]
    scored: bool
    primary_gate: Literal["pass", "fail", "unmeasured"]
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "AnswerKey",
    "AnswerType",
    "BenchmarkItem",
    "BenchmarkMetricSource",
    "BenchmarkMethod",
    "BenchmarkRun",
    "BenchmarkRunMode",
    "BenchmarkSummary",
    "EvidenceSpan",
    "PreparedContext",
    "PricingConfig",
    "ReplayRecord",
    "ScoreRecord",
    "TargetMode",
    "TargetRequest",
    "TargetResponse",
    "TargetSettings",
    "TargetStatus",
    "UsageAccounting",
    "UsageSource",
]
