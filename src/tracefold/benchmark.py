"""Offline-first paired benchmark harness for Phase 7."""

from __future__ import annotations

import math
import os
import re
import statistics
import subprocess
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tracefold.compression import compress_source
from tracefold.cprgc import compress_with_cprgc
from tracefold.extractors import extract_obligations
from tracefold.hashing import sha256_domain
from tracefold.phase6_fixtures import long_fixture_inputs
from tracefold.phase6_report import fixture_registry
from tracefold.phase7_fixtures import build_context_proof_bench, build_controlled_context_stress
from tracefold.schemas.common import FinalAction, HashDomain, TokenizerIdentity
from tracefold.schemas.phase2 import ContentType, ExtractionResult
from tracefold.schemas.phase3 import (
    CompilerStrategy,
    RawCompressionRequest,
)
from tracefold.schemas.phase6 import CPRGCMode, CPRGCResult
from tracefold.schemas.phase7 import (
    AnswerType,
    BenchmarkItem,
    BenchmarkMethod,
    BenchmarkRun,
    BenchmarkRunMode,
    BenchmarkSummary,
    PreparedContext,
    PricingConfig,
    ScoreRecord,
    TargetRequest,
    TargetResponse,
    TargetSettings,
    TargetStatus,
)
from tracefold.serialization import canonical_json_bytes
from tracefold.sources import ingest_source
from tracefold.target import TargetAdapter, build_target_request

BENCHMARK_VERSION = "ContextProofBench-v1"
COMPONENT_VERSION = "tracefold.benchmark/1.0.0"
SYSTEM_PROMPT = (
    "You are answering questions using only supplied context. Return requested answer. "
    "Do not explain unless question requests explanation. If answer absent, "
    "return NOT_FOUND."
)
DEFAULT_METHOD_IDS = (
    "full_context",
    "head_truncation",
    "tail_truncation",
    "head_tail",
    "lexical_top_k",
    "phase3_extract",
    "cprgc_target",
    "cprgc_aggressive",
)
PRIMARY_METHOD_IDS = (
    "full_context",
    "head_tail",
    "lexical_top_k",
    "phase3_extract",
    "cprgc_target",
)
METHODS = (
    BenchmarkMethod(
        method_id="full_context", version="1.0.0", lossy=False, description="Original context."
    ),
    BenchmarkMethod(
        method_id="head_truncation",
        version="1.0.0",
        lossy=True,
        description="First matched local-token units.",
    ),
    BenchmarkMethod(
        method_id="tail_truncation",
        version="1.0.0",
        lossy=True,
        description="Last matched local-token units.",
    ),
    BenchmarkMethod(
        method_id="head_tail",
        version="1.0.0",
        lossy=True,
        description="Matched budget split between context ends.",
    ),
    BenchmarkMethod(
        method_id="lexical_top_k",
        version="1.0.0",
        lossy=True,
        description="Highest deterministic lexical-overlap chunks.",
    ),
    BenchmarkMethod(
        method_id="phase3_extract",
        version="1.0.0",
        lossy=True,
        description="Existing Phase 3 deterministic extractor.",
    ),
    BenchmarkMethod(
        method_id="cprgc_target",
        version="1.0.0",
        lossy=True,
        description="CPRGC target mode with verification/recovery.",
    ),
    BenchmarkMethod(
        method_id="cprgc_aggressive",
        version="1.0.0",
        lossy=True,
        description="CPRGC aggressive mode with verification/recovery.",
    ),
)
METHOD_BY_ID = {item.method_id: item for item in METHODS}
_FIXTURE_REGISTRY = fixture_registry()
FIXTURE_TOKENIZER = _FIXTURE_REGISTRY.resolve(
    next(iter(_FIXTURE_REGISTRY._items.values())).identity
)


def deterministic_run_id(label: str) -> str:
    """Derive UUIDv4-shaped deterministic IDs without runtime randomness."""
    raw = bytearray(__import__("hashlib").sha256(label.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def ratio(original: int, current: int) -> str:
    if original <= 0:
        return "0.000000"
    return f"{max(0.0, min(1.0, 1 - current / original)):.6f}"


def prompt_for(item: BenchmarkItem, context: str) -> tuple[str, str]:
    user = (
        "CONTEXT:\n"
        f"{context}\n\n"
        "QUESTION:\n"
        f"{item.question}\n\n"
        "ANSWER FORMAT:\n"
        f"{item.answer_key.answer_type.value}"
    )
    return SYSTEM_PROMPT, user


def _source_kind(name: str) -> ContentType:
    return {
        "document": ContentType.DOCUMENT,
        "dialogue": ContentType.DIALOGUE,
        "json": ContentType.JSON,
        "logs": ContentType.LOG,
        "python": ContentType.PYTHON,
    }[name]


def _fixture_name(item: BenchmarkItem) -> str:
    return "logs" if item.source_kind == ContentType.LOG else item.source_kind.value


def _token_count(text: str) -> int:
    return FIXTURE_TOKENIZER.count(text)


def _take_prefix(text: str, budget: int) -> str:
    if budget >= _token_count(text):
        return text
    count = 0
    chars: list[str] = []
    for char in text:
        cost = _token_count(char)
        if count + cost > budget:
            break
        chars.append(char)
        count += cost
    return "".join(chars)


def _take_suffix(text: str, budget: int) -> str:
    if budget >= _token_count(text):
        return text
    count = 0
    chars: list[str] = []
    for char in reversed(text):
        cost = _token_count(char)
        if count + cost > budget:
            break
        chars.append(char)
        count += cost
    return "".join(reversed(chars))


def _chunks(text: str) -> list[str]:
    if "\n" in text:
        chunks = [line for line in text.splitlines(keepends=True) if line]
    else:
        chunks = [text[index : index + 240] for index in range(0, len(text), 240)]
    return chunks or [text]


def _lexical_context(text: str, question: str, budget: int) -> str:
    terms = [item for item in re.findall(r"[\w.-]+", question.lower()) if len(item) > 1]
    chunks = _chunks(text)
    ranked = sorted(
        enumerate(chunks),
        key=lambda item: (-sum(item[1].lower().count(term) for term in terms), item[0]),
    )
    selected: list[tuple[int, str]] = []
    cost = 0
    for index, chunk in ranked:
        chunk_cost = _token_count(chunk)
        if selected and cost + chunk_cost > budget:
            continue
        if not selected and chunk_cost > budget:
            return _take_prefix(chunk, budget)
        selected.append((index, chunk))
        cost += chunk_cost
        if cost >= budget:
            break
    return "".join(chunk for _, chunk in sorted(selected))


def _head_tail_context(text: str, budget: int) -> str:
    marker = "\n...\n"
    if budget >= _token_count(text):
        return text
    available = max(0, budget - _token_count(marker))
    head_budget = math.ceil(available / 2)
    tail_budget = available - head_budget
    candidate = _take_prefix(text, head_budget) + marker + _take_suffix(text, tail_budget)
    if _token_count(candidate) <= budget:
        return candidate
    return _take_prefix(text, budget)


def _fallback_context(text: str, budget: int) -> str:
    return _take_prefix(text, budget)


def _extract(source: Any, kind: ContentType) -> ExtractionResult:
    return extract_obligations(source, kind)


def _coverage(result: CPRGCResult) -> tuple[str | None, str | None]:
    report = result.verification_report
    if report is None:
        return None, None
    raw = result.raw_result
    mandatory = sum(item.mandatory for item in raw.obligation_coverage.values())
    verified = 0
    for name, item in raw.obligation_coverage.items():
        verified_item = report.obligation_results.get(name)
        if verified_item is not None:
            verified += min(item.mandatory, verified_item.verified)
    relation_total = sum(item.discovered for item in report.relation_results)
    relation_verified = sum(item.verified for item in report.relation_results)
    return ratio(mandatory, verified) if mandatory else "1.000000", ratio(
        relation_total, relation_verified
    ) if relation_total else "1.000000"


def _cprgc_context(
    item: BenchmarkItem,
    source: Any,
    extraction: ExtractionResult,
    mode: CPRGCMode,
    *,
    query: str | None = None,
) -> tuple[str, CPRGCResult]:
    original = source.raw_bytes.decode("utf-8")
    result = compress_with_cprgc(
        source,
        fixture_registry(),
        query=query,
        mode=mode,
        extraction=extraction,
        run_id=deterministic_run_id(f"{item.item_id}:{mode.value}"),
        maximum_attempts=3,
        maximum_final_token_budget=max(_token_count(original), 1),
    )
    context = result.context or original
    return context, result


def _prepared(
    item: BenchmarkItem,
    method_id: str,
    context: str,
    original_count: int,
    budget: int,
    *,
    result: CPRGCResult | None = None,
) -> PreparedContext:
    context_count = _token_count(context)
    raw_reduction = result.diagnostics.raw_reduction if result is not None else None
    final_reduction = (
        result.diagnostics.final_reduction
        if result is not None
        else ratio(original_count, context_count)
    )
    requested_reduction = (
        result.diagnostics.requested_reduction
        if result is not None
        else ratio(original_count, budget)
    )
    status = result.status.value if result is not None else "baseline"
    action = result.final_action if result is not None else FinalAction.EMIT
    certificate_hash = None
    hard_coverage = None
    relation_coverage = None
    warnings: list[str] = []
    if result is not None:
        if result.certificate is not None and hasattr(result.certificate, "certificate_hash"):
            certificate_hash = result.certificate.certificate_hash
        hard_coverage, relation_coverage = _coverage(result)
        warnings = result.warnings
    return PreparedContext(
        item_id=item.item_id,
        method_id=method_id,
        context=context,
        original_token_count=original_count,
        context_token_count=context_count,
        matched_budget=max(1, budget),
        requested_reduction=requested_reduction,
        raw_reduction=raw_reduction,
        final_reduction=final_reduction,
        compression_status=status,
        final_action=action,
        certificate_hash=certificate_hash,
        verification_status=(
            result.verification_report.status.value
            if result and result.verification_report
            else "not_run"
        ),
        hard_obligation_coverage=hard_coverage,
        relation_coverage=relation_coverage,
        fallback=action == FinalAction.FULL_FALLBACK,
        warnings=warnings,
    )


def prepare_contexts(
    items: Iterable[BenchmarkItem],
    *,
    method_ids: Iterable[str] = DEFAULT_METHOD_IDS,
) -> tuple[PreparedContext, ...]:
    selected_methods = tuple(method_ids)
    unknown = sorted(set(selected_methods) - set(METHOD_BY_ID))
    if unknown:
        raise ValueError(f"unknown benchmark methods: {unknown}")
    source_inputs = {name: ingest_source(item) for name, item in long_fixture_inputs().items()}
    extractions = {
        name: _extract(source_inputs[name], _source_kind(name))
        for name in source_inputs
        if name != "dense"
    }
    needs_target = bool(
        {"cprgc_target", "cprgc_aggressive", "phase3_extract"} & set(selected_methods)
    )
    compression_by_source: dict[
        str, tuple[str, CPRGCResult | None, str, CPRGCResult | None, int]
    ] = {}
    target_context: str
    target_result: CPRGCResult | None
    aggressive_context: str
    aggressive_result: CPRGCResult | None
    budget: int
    if needs_target:
        first_items = {_fixture_name(item): item for item in items}
        for source_name, item in sorted(first_items.items()):
            source = source_inputs[source_name]
            extraction = extractions[source_name]
            target_context, target_result = _cprgc_context(
                item, source, extraction, CPRGCMode.TARGET
            )
            aggressive_context, aggressive_result = _cprgc_context(
                item, source, extraction, CPRGCMode.AGGRESSIVE
            )
            original_count = _token_count(source.raw_bytes.decode("utf-8"))
            compression_by_source[source_name] = (
                target_context,
                target_result,
                aggressive_context,
                aggressive_result,
                target_result.diagnostics.final_tokens or original_count,
            )
    records: list[PreparedContext] = []
    for item in items:
        source_name = _fixture_name(item)
        source = source_inputs[source_name]
        extraction = extractions[source_name]
        original = source.raw_bytes.decode("utf-8")
        original_count = _token_count(original)
        if needs_target:
            target_context, target_result, aggressive_context, aggressive_result, budget = (
                compression_by_source[source_name]
            )
        else:
            target_context, target_result = original, None
            aggressive_context, aggressive_result, budget = original, None, original_count
        for method_id in selected_methods:
            if method_id == "full_context":
                records.append(_prepared(item, method_id, original, original_count, budget))
            elif method_id == "head_truncation":
                records.append(
                    _prepared(
                        item, method_id, _fallback_context(original, budget), original_count, budget
                    )
                )
            elif method_id == "tail_truncation":
                records.append(
                    _prepared(
                        item, method_id, _take_suffix(original, budget), original_count, budget
                    )
                )
            elif method_id == "head_tail":
                records.append(
                    _prepared(
                        item,
                        method_id,
                        _head_tail_context(original, budget),
                        original_count,
                        budget,
                    )
                )
            elif method_id == "lexical_top_k":
                records.append(
                    _prepared(
                        item,
                        method_id,
                        _lexical_context(original, item.question, budget),
                        original_count,
                        budget,
                    )
                )
            elif method_id == "phase3_extract":
                request = RawCompressionRequest(
                    run_id=deterministic_run_id(f"{item.item_id}:phase3"),
                    source_id=source.source_id,
                    source_kind=item.source_kind,
                    tokenizer_id=FIXTURE_TOKENIZER.identity,
                    target_token_budget=budget,
                    compiler_strategy=CompilerStrategy.DETERMINISTIC_EXTRACTIVE,
                )
                phase3 = compress_source(request, source, fixture_registry(), extraction)
                phase3_context = phase3.compressed_text or original
                records.append(_prepared(item, method_id, phase3_context, original_count, budget))
            elif method_id == "cprgc_target":
                if target_result is None:
                    raise ValueError("CPRGC target preparation was not requested")
                records.append(
                    _prepared(
                        item,
                        method_id,
                        target_context,
                        original_count,
                        budget,
                        result=target_result,
                    )
                )
            elif method_id == "cprgc_aggressive":
                if aggressive_result is None:
                    raise ValueError("CPRGC aggressive preparation was not requested")
                aggressive_budget = aggressive_result.diagnostics.final_tokens or original_count
                records.append(
                    _prepared(
                        item,
                        method_id,
                        aggressive_context,
                        original_count,
                        aggressive_budget,
                        result=aggressive_result,
                    )
                )
    return tuple(records)


def _normalize(text: str, *, case_sensitive: bool) -> str:
    value = unicodedata.normalize("NFC", text).strip()
    return value if case_sensitive else value.casefold()


def _number_value(text: str) -> Decimal | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w'-]+", _normalize(text, case_sensitive=False))


def _f1(predicted: str, expected: str) -> float:
    left, right = Counter(_tokens(predicted)), Counter(_tokens(expected))
    common = sum((left & right).values())
    if not left or not right:
        return 1.0 if predicted.strip() == expected.strip() else 0.0
    precision = common / sum(left.values())
    recall = common / sum(right.values())
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def score_answer(item: BenchmarkItem, response: TargetResponse) -> tuple[bool, float, bool]:
    if response.status != TargetStatus.SUCCESS or response.answer_text is None:
        return False, 0.0, True
    answer = response.answer_text
    key = item.answer_key
    if key.answer_type in {AnswerType.NUMBER, AnswerType.NUMBER_WITH_UNIT}:
        numeric_value = _number_value(answer)
        expected = Decimal(key.exact_numeric_answer or "nan")
        correct = numeric_value == expected
        if correct and key.required_units:
            correct = all(unit.casefold() in answer.casefold() for unit in key.required_units)
        return correct, float(correct), False
    if key.answer_type == AnswerType.DATE:
        date_match = re.search(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?", answer)
        correct = date_match is not None and any(
            date_match.group(0) == accepted for accepted in key.accepted_answers
        )
        return correct, float(correct), False
    if key.answer_type == AnswerType.SHORT_FREE_TEXT:
        scores = [_f1(answer, expected) for expected in key.accepted_answers]
        f1_score = max(scores, default=0.0)
        return f1_score >= 0.8, f1_score, False
    if key.answer_type == AnswerType.ORDERED_LIST:
        predicted = [
            _normalize(part, case_sensitive=False)
            for part in re.split(r"[,;|]", answer)
            if part.strip()
        ]
        expected_list = [
            _normalize(part, case_sensitive=False)
            for part in re.split(r"[,;|]", key.accepted_answers[0])
            if part.strip()
        ]
        return predicted == expected_list, float(predicted == expected_list), False
    if key.answer_type == AnswerType.SET:
        predicted_set = {
            _normalize(part, case_sensitive=False)
            for part in re.split(r"[,;|]", answer)
            if part.strip()
        }
        expected_set = {
            _normalize(part, case_sensitive=False)
            for part in re.split(r"[,;|]", key.accepted_answers[0])
            if part.strip()
        }
        return predicted_set == expected_set, float(predicted_set == expected_set), False
    accepted = {
        _normalize(value, case_sensitive=key.case_sensitive) for value in key.accepted_answers
    }
    return (
        _normalize(answer, case_sensitive=key.case_sensitive) in accepted,
        float(_normalize(answer, case_sensitive=key.case_sensitive) in accepted),
        False,
    )


def _price(tokens: int | None, per_million: float | None) -> float | None:
    if tokens is None or per_million is None:
        return None
    return tokens * per_million / 1_000_000


def score_record(
    item: BenchmarkItem,
    prepared: PreparedContext,
    response: TargetResponse,
    *,
    full_context_correct: bool | None,
    pricing: PricingConfig | None = None,
    end_to_end_latency_ms: float | None = None,
) -> ScoreRecord:
    correct, score, infrastructure = score_answer(item, response)
    input_cost = _price(
        response.input_tokens, pricing.input_price_per_million_tokens if pricing else None
    )
    output_cost = _price(
        response.output_tokens, pricing.output_price_per_million_tokens if pricing else None
    )
    total_cost = (
        input_cost + output_cost if input_cost is not None and output_cost is not None else None
    )
    return ScoreRecord(
        item_id=item.item_id,
        method_id=prepared.method_id,
        source_kind=item.source_kind,
        answer_type=item.answer_key.answer_type,
        target_response=response,
        correct=correct,
        score=score,
        full_context_correct=full_context_correct,
        infrastructure_failure=infrastructure,
        original_token_count=prepared.original_token_count,
        context_token_count=prepared.context_token_count,
        input_reduction=ratio(prepared.original_token_count, prepared.context_token_count),
        raw_reduction=prepared.raw_reduction,
        final_reduction=prepared.final_reduction,
        target_latency_ms=response.request_latency_ms,
        end_to_end_latency_ms=end_to_end_latency_ms,
        input_cost=input_cost,
        output_cost=output_cost,
        total_cost=total_cost,
        status=response.status.value,
    )


def _request_for(
    item: BenchmarkItem, prepared: PreparedContext, settings: TargetSettings
) -> TargetRequest:
    system, user = prompt_for(item, prepared.context)
    return build_target_request(
        request_id=deterministic_run_id(f"{BENCHMARK_VERSION}:{item.item_id}:{prepared.method_id}"),
        benchmark_item_id=item.item_id,
        method_id=prepared.method_id,
        model_id=settings.model_id,
        system_prompt=system,
        user_prompt=user,
        context=prepared.context,
        temperature=settings.temperature,
        maximum_output_tokens=settings.maximum_output_tokens,
        seed=settings.seed,
        timeout_seconds=settings.request_timeout_seconds,
        metadata={"benchmark_version": BENCHMARK_VERSION, "source_kind": item.source_kind.value},
    )


def run_benchmark(
    items: Iterable[BenchmarkItem],
    prepared: Iterable[PreparedContext],
    adapter: TargetAdapter,
    *,
    pricing: PricingConfig | None = None,
) -> tuple[ScoreRecord, ...]:
    item_by_id = {item.item_id: item for item in items}
    prepared_records = tuple(prepared)
    settings = adapter.settings
    responses: dict[tuple[str, str], TargetResponse] = {}
    requests: dict[tuple[str, str], TargetRequest] = {}
    for record in prepared_records:
        item = item_by_id[record.item_id]
        request = _request_for(item, record, settings)
        requests[(record.item_id, record.method_id)] = request
        responses[(record.item_id, record.method_id)] = adapter.invoke(request)
    full_correct: dict[str, bool | None] = {}
    for record in prepared_records:
        if record.method_id == "full_context":
            response = responses[(record.item_id, record.method_id)]
            full_correct[record.item_id] = score_answer(item_by_id[record.item_id], response)[0]
    result: list[ScoreRecord] = []
    for record in prepared_records:
        response = responses[(record.item_id, record.method_id)]
        result.append(
            score_record(
                item_by_id[record.item_id],
                record,
                response,
                full_context_correct=full_correct.get(record.item_id),
                pricing=pricing,
                end_to_end_latency_ms=response.request_latency_ms,
            )
        )
    return tuple(result)


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    center = (successes + z * z / 2) / (total + z * z)
    margin = z * math.sqrt(successes * (total - successes) / total + z * z / 4) / (total + z * z)
    return max(0.0, center - margin), min(1.0, center + margin)


def summarize_scores(scores: Iterable[ScoreRecord]) -> dict[str, Any]:
    records = tuple(scores)
    by_method: dict[str, list[ScoreRecord]] = defaultdict(list)
    by_kind: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
    for record in records:
        by_method[record.method_id].append(record)
        by_kind[(record.method_id, record.source_kind.value)].append(record)
    full = {
        item.item_id: item.correct
        for item in by_method.get("full_context", [])
        if not item.infrastructure_failure
    }
    methods: dict[str, Any] = {}
    for method_id, values in sorted(by_method.items()):
        valid = [item for item in values if not item.infrastructure_failure]
        correct = sum(item.correct for item in valid)
        denominator = len(valid)
        full_correct_count = sum(full.values())
        paired = sum(item.correct and full.get(item.item_id, False) for item in valid)
        low, high = wilson_interval(correct, denominator)
        paired_low, paired_high = wilson_interval(paired, full_correct_count)
        methods[method_id] = {
            "correct": correct,
            "denominator": denominator,
            "accuracy": correct / denominator if denominator else None,
            "accuracy_wilson_95": [low, high],
            "paired_correct": paired,
            "paired_denominator_full_correct": full_correct_count,
            "paired_retention": paired / full_correct_count if full_correct_count else None,
            "paired_retention_wilson_95": [paired_low, paired_high],
            "infrastructure_failures": len(values) - denominator,
            "mean_reduction": statistics.fmean(float(item.input_reduction or 0) for item in values)
            if values
            else 0.0,
            "per_kind": {
                kind: _kind_metrics(items, full)
                for (method, kind), items in sorted(by_kind.items())
                if method == method_id
            },
        }
    disagreements: dict[str, dict[str, int]] = {}
    for method_id, values in sorted(by_method.items()):
        if method_id == "full_context":
            continue
        pairs = [
            item for item in values if item.item_id in full and not item.infrastructure_failure
        ]
        disagreements[method_id] = {
            "compressed_wrong_full_correct": sum(
                not item.correct and full[item.item_id] for item in pairs
            ),
            "compressed_correct_full_wrong": sum(
                item.correct and not full[item.item_id] for item in pairs
            ),
            "ties": sum(item.correct == full[item.item_id] for item in pairs),
        }
    return {"methods": methods, "paired_disagreements": disagreements, "record_count": len(records)}


def _kind_metrics(values: list[ScoreRecord], full: dict[str, bool]) -> dict[str, Any]:
    valid = [item for item in values if not item.infrastructure_failure]
    denominator = len(valid)
    full_denominator = sum(full.get(item.item_id, False) for item in valid)
    paired = sum(item.correct and full.get(item.item_id, False) for item in valid)
    low, high = wilson_interval(paired, full_denominator)
    return {
        "correct": sum(item.correct for item in valid),
        "denominator": denominator,
        "accuracy": sum(item.correct for item in valid) / denominator if denominator else None,
        "paired_correct": paired,
        "paired_denominator_full_correct": full_denominator,
        "paired_retention": paired / full_denominator if full_denominator else None,
        "paired_retention_wilson_95": [low, high],
        "mean_reduction": statistics.fmean(float(item.input_reduction or 0) for item in valid)
        if valid
        else 0.0,
    }


def structural_summary(prepared: Iterable[PreparedContext]) -> dict[str, Any]:
    values = tuple(prepared)
    return {
        "record_count": len(values),
        "mean_context_reduction": statistics.fmean(
            float(item.final_reduction or item.raw_reduction or "0") for item in values
        )
        if values
        else 0.0,
    }


def default_pricing(model_id: str = "unconfigured") -> PricingConfig:
    return PricingConfig(
        model_id=model_id,
        currency="USD",
        pricing_effective_date="unset",
        pricing_source_note="User-supplied pricing required; monetary fields remain null.",
    )


def prepare_artifacts(
    output_dir: str | Path,
    *,
    items: tuple[BenchmarkItem, ...] | None = None,
    method_ids: Iterable[str] = DEFAULT_METHOD_IDS,
) -> dict[str, Any]:
    directory = Path(output_dir)
    selected_methods = tuple(method_ids)
    directory.mkdir(parents=True, exist_ok=True)
    benchmark_items = items or build_context_proof_bench()
    prepared = prepare_contexts(benchmark_items, method_ids=selected_methods)
    _write_jsonl(directory / "benchmark-items.jsonl", benchmark_items)
    _write_jsonl(directory / "controlled-context-stress.jsonl", build_controlled_context_stress())
    _write_json(
        directory / "benchmark-methods.json",
        [
            item.model_dump(mode="json")
            for item in METHODS
            if item.method_id in set(selected_methods)
        ],
    )
    _write_jsonl(directory / "prepared-contexts.jsonl", prepared)
    (directory / "scored-results.jsonl").write_text("", encoding="utf-8")
    pricing = default_pricing()
    _write_json(directory / "pricing-config.example.json", pricing.model_dump(mode="json"))
    run = _manifest(
        mode=BenchmarkRunMode.PREPARE,
        item_count=len(benchmark_items),
        method_ids=selected_methods,
        model_id="unconfigured",
        pricing_config=pricing,
    )
    _write_json(directory / "run-manifest.json", run.model_dump(mode="json"))
    summary = BenchmarkSummary(
        benchmark_version=BENCHMARK_VERSION,
        mode=BenchmarkRunMode.PREPARE,
        item_count=len(benchmark_items),
        method_count=len(selected_methods),
        expected_request_count=len(benchmark_items) * len(selected_methods),
        live_request_count=0,
        infrastructure_failure_count=0,
        structural_reduction_by_kind={
            kind: ratio(
                sum(
                    item.original_token_count
                    for item in prepared
                    if item.method_id == "cprgc_target"
                    and _item_kind(benchmark_items, item.item_id) == kind
                ),
                sum(
                    item.context_token_count
                    for item in prepared
                    if item.method_id == "cprgc_target"
                    and _item_kind(benchmark_items, item.item_id) == kind
                ),
            )
            for kind in sorted(
                {
                    _item_kind(benchmark_items, item.item_id)
                    for item in prepared
                    if item.method_id == "cprgc_target"
                }
            )
        },
        scored=False,
        primary_gate="unmeasured",
        warnings=["Target-model responses absent; downstream accuracy is unmeasured."],
    )
    _write_json(directory / "summary.json", summary.model_dump(mode="json"))
    return {"items": benchmark_items, "prepared": prepared, "summary": summary}


def _item_kind(items: Iterable[BenchmarkItem], item_id: str) -> str:
    return next(item.source_kind.value for item in items if item.item_id == item_id)


def _manifest(
    *,
    mode: BenchmarkRunMode,
    item_count: int,
    method_ids: tuple[str, ...],
    model_id: str,
    pricing_config: PricingConfig | None = None,
) -> BenchmarkRun:
    commit = "unknown"
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    identity = FIXTURE_TOKENIZER.identity
    try:
        dirty_state = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        dirty_state = False
    return BenchmarkRun(
        run_id=deterministic_run_id(
            f"{BENCHMARK_VERSION}:{mode.value}:{model_id}:{','.join(method_ids)}"
        ),
        benchmark_version=BENCHMARK_VERSION,
        mode=mode,
        model_id=model_id,
        endpoint_class="openai_compatible",
        tokenizer_identity=TokenizerIdentity.model_validate(identity.model_dump(mode="json")),
        item_count=item_count,
        method_ids=list(method_ids),
        request_count=item_count * len(method_ids),
        run_timestamp=datetime(2000, 1, 1, tzinfo=UTC)
        if mode == BenchmarkRunMode.PREPARE
        else datetime.now(UTC),
        pricing_config_hash=(
            sha256_domain(
                HashDomain.CONTEXT_ARTIFACT,
                canonical_json_bytes(pricing_config.model_dump(mode="json")),
            )
            if pricing_config is not None
            else None
        ),
        random_seed=0,
        failures=[],
        environment_summary={
            "git_commit": commit,
            "python": sys.version.split()[0],
            "api_mode": os.getenv("TRACEFOLD_API_MODE", "disabled"),
            "component_version": COMPONENT_VERSION,
            "dirty_state": str(dirty_state),
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _write_jsonl(path: Path, values: Iterable[Any]) -> None:
    path.write_text(
        "".join(
            canonical_json_bytes(
                value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            ).decode("utf-8")
            + "\n"
            for value in values
        ),
        encoding="utf-8",
    )


__all__ = [
    "BENCHMARK_VERSION",
    "COMPONENT_VERSION",
    "DEFAULT_METHOD_IDS",
    "METHODS",
    "PRIMARY_METHOD_IDS",
    "TargetAdapter",
    "build_context_proof_bench",
    "build_target_request",
    "default_pricing",
    "deterministic_run_id",
    "prepare_artifacts",
    "prepare_contexts",
    "prompt_for",
    "run_benchmark",
    "score_answer",
    "score_record",
    "summarize_scores",
    "wilson_interval",
]
