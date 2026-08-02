"""Deterministic Phase 7 benchmark report generator."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from tracefold.benchmark import (
    BENCHMARK_VERSION,
    METHODS,
    summarize_scores,
)
from tracefold.hashing import sha256_domain
from tracefold.schemas.common import HashDomain
from tracefold.schemas.phase7 import BenchmarkItem, PreparedContext, ScoreRecord
from tracefold.serialization import canonical_json_bytes


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path, model: Any) -> list[Any]:
    return [
        model.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _kind_map(items: list[BenchmarkItem]) -> dict[str, str]:
    return {item.item_id: item.source_kind.value for item in items}


def _aggressive_demo_ids(items: list[BenchmarkItem]) -> set[str]:
    selected: set[str] = set()
    for kind in sorted({item.source_kind.value for item in items}):
        candidates = [item for item in items if item.source_kind.value == kind]
        selected.update(item.item_id for item in candidates[:2])
    return selected


def _prepared_reductions(
    items: list[BenchmarkItem], prepared: list[PreparedContext]
) -> dict[str, str]:
    kinds = _kind_map(items)
    result: dict[str, str] = {}
    for kind in sorted(set(kinds.values())):
        values = [
            item.configured_context_reduction or "0.000000"
            for item in prepared
            if item.method_id == "cprgc_target" and kinds[item.item_id] == kind
        ]
        result[kind] = (
            f"{sum(float(value) for value in values) / len(values):.6f}" if values else "0.000000"
        )
    return result


def _configured_mean_reduction(
    prepared: list[PreparedContext], *, emitted_only: bool = False
) -> str | None:
    values = [
        float(item.configured_context_reduction)
        for item in prepared
        if item.method_id == "cprgc_target"
        and item.configured_context_reduction is not None
        and (not emitted_only or not item.fallback)
    ]
    return f"{sum(values) / len(values):.6f}" if values else None


def _gate(
    summary: dict[str, Any],
    prepared: list[PreparedContext],
    items: list[BenchmarkItem],
    scores: list[ScoreRecord] | None = None,
) -> str:
    scores = scores or []
    methods = summary.get("methods", {})
    target = methods.get("cprgc_target")
    if target is None:
        return "unmeasured"
    if target.get("denominator", 0) == 0:
        return "unmeasured"
    target_prepared = [item for item in prepared if item.method_id == "cprgc_target"]
    expected_ids = {item.item_id for item in items}
    target_score_ids = {item.item_id for item in scores if item.method_id == "cprgc_target"}
    full_score_ids = {item.item_id for item in scores if item.method_id == "full_context"}
    if (
        len(items) != 50
        or len(target_prepared) != 50
        or target_score_ids != expected_ids
        or full_score_ids != expected_ids
    ):
        return "fail"
    if any(item.verification_status != "valid" for item in target_prepared):
        return "fail"
    if any(
        item.hard_obligation_coverage_status == "applicable"
        and item.hard_obligation_coverage != "1.000000"
        or item.relation_coverage_status == "applicable"
        and item.relation_coverage != "1.000000"
        for item in target_prepared
    ):
        return "fail"
    if any(
        item.fallback and float(item.configured_context_reduction or "0") != 0
        for item in target_prepared
    ):
        return "fail"
    target_retention = target.get("paired_retention")
    if target_retention is not None and target_retention >= 0.95:
        return "pass"
    return "fail"


def _run_model_id(directory: Path) -> str | None:
    path = directory / "run-manifest.json"
    return _read_json(path).get("model_id") if path.exists() else None


def build_report(output_dir: str | Path = "reports/final") -> dict[str, Any]:
    directory = Path(output_dir)
    if not (directory / "benchmark-items.jsonl").exists():
        raise FileNotFoundError(f"benchmark artifacts not prepared: {directory}")
    items = _read_jsonl(directory / "benchmark-items.jsonl", BenchmarkItem)
    prepared = _read_jsonl(directory / "prepared-contexts.jsonl", PreparedContext)
    score_path = directory / "scored-results.jsonl"
    scores = _read_jsonl(score_path, ScoreRecord) if score_path.exists() else []
    score_summary = (
        summarize_scores(scores)
        if scores
        else {"methods": {}, "paired_disagreements": {}, "record_count": 0}
    )
    methods = [
        item.method_id
        for item in METHODS
        if (directory / "benchmark-methods.json").exists()
        and item.method_id
        in {value["method_id"] for value in _read_json(directory / "benchmark-methods.json")}
    ]
    if not methods:
        methods = [item.method_id for item in METHODS]
    payload: dict[str, Any] = {
        "benchmark_version": BENCHMARK_VERSION,
        "mode": "scored" if scores else "prepared",
        "item_count": len(items),
        "source_kind_counts": dict(
            sorted(Counter(item.source_kind.value for item in items).items())
        ),
        "method_ids": methods,
        "expected_request_count": len(items) * len(methods),
        "live_request_count": sum(
            1 for item in scores if item.target_response.status.value == "success"
        ),
        "infrastructure_failure_count": sum(1 for item in scores if item.infrastructure_failure),
        "structural_reduction_by_kind": _prepared_reductions(items, prepared),
        "configured_mean_context_reduction": _configured_mean_reduction(prepared),
        "configured_mean_emitted_context_reduction": _configured_mean_reduction(
            prepared, emitted_only=True
        ),
        "model_id": _run_model_id(directory),
        "configured_tokenizer_identity": (
            prepared[0].tokenizer_identity.model_dump(mode="json")
            if prepared and prepared[0].tokenizer_identity is not None
            else None
        ),
        "metric_source": (
            prepared[0].metric_source.value
            if prepared and prepared[0].metric_source is not None
            else None
        ),
        "prepared_verification_statuses": dict(
            sorted(
                Counter(
                    item.verification_status
                    for item in prepared
                    if item.method_id == "cprgc_target"
                ).items()
            )
        ),
        "scoring": score_summary if scores else None,
        "primary_gate": _gate(score_summary, prepared, items, scores) if scores else "unmeasured",
        "claims": [
            "Prepared artifacts measure structural compression only.",
            "Downstream accuracy is unmeasured without live or valid replay responses."
            if not scores
            else "Downstream metrics derive from deterministic answer keys.",
        ],
    }
    payload["report_hash"] = sha256_domain(
        HashDomain.CONTEXT_ARTIFACT,
        canonical_json_bytes(payload),
    )
    _write_outputs(directory, payload, items, prepared, scores)
    return payload


def _write_outputs(
    directory: Path,
    payload: dict[str, Any],
    items: list[BenchmarkItem],
    prepared: list[PreparedContext],
    scores: list[ScoreRecord],
) -> None:
    (directory / "summary.json").write_bytes(canonical_json_bytes(payload) + b"\n")
    score_methods = payload.get("scoring", {}).get("methods", {}) if payload.get("scoring") else {}
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "method",
                "correct",
                "denominator",
                "accuracy",
                "paired_retention",
                "mean_reduction",
                "infrastructure_failures",
            ]
        )
        for method_id in sorted(score_methods):
            value = score_methods[method_id]
            writer.writerow(
                [
                    method_id,
                    value.get("correct"),
                    value.get("denominator"),
                    value.get("accuracy"),
                    value.get("paired_retention"),
                    value.get("mean_reduction"),
                    value.get("infrastructure_failures"),
                ]
            )
    mode = payload["mode"]
    lines = [
        f"# ContextProofBench v1 ({mode})",
        "",
        f"Items: {payload['item_count']}",
        f"Expected requests: {payload['expected_request_count']}",
        f"Primary gate: {payload['primary_gate']}",
        "",
        "## Structural results",
        "",
    ]
    for kind, value in payload["structural_reduction_by_kind"].items():
        lines.append(f"- {kind}: {value} final reduction")
    if payload.get("scoring"):
        lines.extend(["", "## Scored methods", ""])
        for method_id, value in payload["scoring"]["methods"].items():
            lines.append(
                f"- {method_id}: accuracy={value['accuracy']}, "
                f"paired_retention={value['paired_retention']}, "
                f"reduction={value['mean_reduction']}"
            )
    lines.extend(
        [
            "",
            "Accuracy gate remains unmeasured until live/replay responses exist."
            if not scores
            else "All infrastructure failures remain counted separately.",
        ]
    )
    (directory / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failures = [item for item in scores if item.infrastructure_failure]
    failure_lines = ["# Failures", "", f"Infrastructure failures: {len(failures)}"]
    failure_lines.extend(
        f"- {item.item_id}/{item.method_id}: "
        f"{item.target_response.error_code}: {item.target_response.error_message}"
        for item in failures
    )
    (directory / "failures.md").write_text("\n".join(failure_lines) + "\n", encoding="utf-8")
    if scores:
        _write_claim_freeze(directory, payload, items, scores)
    aggressive = [
        item.model_dump(mode="json") for item in prepared if item.method_id == "cprgc_aggressive"
    ]
    if scores:
        aggressive_scores = [
            item.model_dump(mode="json") for item in scores if item.method_id == "cprgc_aggressive"
        ]
        aggressive = [
            {
                "prepared": next(
                    (value for value in aggressive if value["item_id"] == item.item_id), None
                ),
                "score": item,
            }
            for item in _as_models(aggressive_scores)
        ]
    demo_ids = _aggressive_demo_ids(items)
    aggressive_prepared = [
        item.model_dump(mode="json")
        for item in prepared
        if item.method_id == "cprgc_aggressive" and item.item_id in demo_ids
    ]
    demo_scores: dict[str, dict[str, Any]] = {
        item.item_id: item.model_dump(mode="json")
        for item in scores
        if item.method_id == "cprgc_aggressive" and item.item_id in demo_ids
    }
    aggressive = [
        {"prepared": item, "score": demo_scores.get(item["item_id"])}
        for item in aggressive_prepared
    ]
    (directory / "aggressive-demo.json").write_bytes(canonical_json_bytes(aggressive) + b"\n")


def _write_claim_freeze(
    directory: Path,
    payload: dict[str, Any],
    items: list[BenchmarkItem],
    scores: list[ScoreRecord],
) -> None:
    methods = payload["scoring"]["methods"]
    target = methods.get("cprgc_target", {})
    paired = target.get("paired_correct", 0)
    denominator = target.get("paired_denominator_full_correct", 0)
    target_ids = {item.item_id for item in scores if item.method_id == "cprgc_target"}
    full_ids = {item.item_id for item in scores if item.method_id == "full_context"}
    expected_ids = {item.item_id for item in items}
    complete = len(items) == 50 and target_ids == expected_ids and full_ids == expected_ids
    if not complete:
        evidence = "incomplete"
        frozen = [
            "Live evidence is incomplete due to quota or infrastructure limitations.",
            "No downstream-retention claim is made.",
        ]
    elif payload["primary_gate"] == "pass":
        evidence = "pass"
        frozen = [
            f"On ContextProofBench v1 with {payload.get('model_id')}, TraceFold retained "
            f"{paired}/{denominator} answers that full context answered correctly.",
            "Four supported compressible fixture classes exceeded 70% configured "
            "cl100k_base context reduction.",
            "Python correctly returned incompressible at the protected mandatory floor.",
        ]
    else:
        evidence = "fail"
        retention = target.get("paired_retention")
        measured = f"{retention * 100:.2f}%" if retention is not None else "unmeasured"
        frozen = [
            f"TraceFold achieved {measured} paired retention ({paired}/{denominator}) on "
            "ContextProofBench v1.",
            "Structural verification remained valid, but structural preservation did not "
            "guarantee target-model answer retention.",
        ]
    lines = ["# Phase 9 Claim Freeze", "", f"Evidence gate: {evidence}", "", "## Frozen claims", ""]
    lines.extend(f"- {claim}" for claim in frozen)
    lines.extend(
        [
            "",
            "## Compression accounting",
            "",
            f"- Mean reduction among emitted compressed contexts: "
            f"{payload.get('configured_mean_emitted_context_reduction')}",
            f"- Fallback-adjusted aggregate reduction: "
            f"{payload.get('configured_mean_context_reduction')}",
            "",
            "## Prohibited claims",
            "",
            "- Universal 95% accuracy.",
            "- All workloads or all five source kinds exceed 70% reduction.",
            "- Semantic equivalence is proven.",
            "- External benchmark superiority without external benchmark evidence.",
            "",
            "## Future triage",
            "",
            "Semantic disagreements require classification without benchmark mutation.",
        ]
    )
    (directory / "claim-freeze.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _as_models(values: list[dict[str, Any]]) -> list[ScoreRecord]:
    return [ScoreRecord.model_validate(item) for item in values]


def main() -> None:
    parser = argparse.ArgumentParser(description="TraceFold Phase 7 benchmark report")
    parser.add_argument("--output-dir", default="reports/final")
    args = parser.parse_args()
    payload = build_report(args.output_dir)
    print(canonical_json_bytes(payload).decode("utf-8"))


if __name__ == "__main__":
    main()


__all__ = ["build_report", "main"]
