"""Export deterministic UI data from Phase 9 evidence and local TraceFold runs."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from tracefold.cprgc import compress_with_cprgc
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source
from tracefold.tokenizers import TokenizerRegistry, resolve_tokenizer

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT / "reports" / "runs" / "phase9-gemini-primary"
SMOKE = ROOT / "reports" / "runs" / "phase9-gemini-smoke"
OUTPUT = ROOT / "web" / "public" / "demo-data" / "index.json"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def deterministic_run_id(value: str) -> str:
    digest = bytearray(hashlib.sha256(value.encode()).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def metric(value: float | None, scope: str, tokenizer: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": "configured_tokenizer",
        "scope": scope,
        "counterIdentity": tokenizer,
        "modelIdentity": None,
        "synthetic": False,
    }


def count(value: int | None, tokenizer: str) -> dict[str, Any]:
    return {
        "value": value,
        "source": "configured_tokenizer",
        "counterIdentity": tokenizer,
        "synthetic": False,
    }


def size(label: str, text: str, token_count: int | None, tokenizer: str) -> dict[str, Any]:
    return {
        "label": label,
        "bytes": len(text.encode()),
        "tokens": count(token_count, tokenizer),
    }


def coverage(
    verified: int | None,
    discovered: int | None,
    mandatory: int | None,
    meaning: str,
    note: str,
) -> dict[str, Any]:
    return {
        "verified": verified,
        "discovered": discovered,
        "mandatory": mandatory,
        "denominatorMeaning": meaning,
        "sourceNote": note,
    }


def tokenizer_label(identity: dict[str, Any]) -> str:
    return f"{identity['implementation']}/{identity['identifier']}@{identity['revision']}"


def line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def actual_lineage(
    source_text: str,
    compact_text: str,
    source_map: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if source_map is None:
        return [], []
    artifacts = {item["artifact_id"]: item["stage"] for item in source_map["artifacts"]}
    spans = {item["span_id"]: item for item in source_map["spans"]}
    source_spans: dict[str, dict[str, Any]] = {}
    fragments: list[dict[str, Any]] = []
    for mapping in source_map["mappings"]:
        from_spans = [spans[item] for item in mapping["from_span_ids"]]
        to_spans = [spans[item] for item in mapping["to_span_ids"]]
        originals = [item for item in from_spans if artifacts[item["artifact_id"]] == "original"]
        compact = [
            item
            for item in to_spans
            if artifacts[item["artifact_id"]] in {"raw_compressed", "final_repaired"}
        ]
        if not originals or not compact:
            continue
        for source_span in originals:
            start = source_span["char_start"]
            end = source_span["char_end"]
            source_spans[source_span["span_id"]] = {
                "id": source_span["span_id"],
                "sourceId": next(
                    item["source_id"]
                    for item in source_map["artifacts"]
                    if item["artifact_id"] == source_span["artifact_id"]
                ),
                "sourceStart": start,
                "sourceEnd": end,
                "lineStart": source_span["line_start"],
                "lineEnd": source_span["line_end"],
                "text": source_text[start:end],
            }
        for compact_span in compact:
            start = compact_span["char_start"]
            end = compact_span["char_end"]
            output_kind = (
                "compact_exact_relation"
                if mapping["relation_ids"]
                else (
                    "exact_copy"
                    if mapping["transform"] == "exact_copy"
                    else (
                        "restored_span"
                        if mapping["transform"] == "restore"
                        else (
                            "synthesized_marker"
                            if compact_span["kind"] == "synthesized"
                            else "deterministic_aggregate"
                        )
                    )
                )
            )
            mapping_type = "one_to_one"
            if len(originals) > 1:
                mapping_type = "many_to_one"
            elif len(compact) > 1:
                mapping_type = "one_to_many"
            fragments.append(
                {
                    "id": mapping["mapping_id"] + f":{start}",
                    "text": compact_text[start:end],
                    "lineStart": compact_span["line_start"],
                    "lineEnd": compact_span["line_end"],
                    "sourceIds": sorted(
                        {source_spans[item["span_id"]]["sourceId"] for item in originals}
                    ),
                    "sourceSpanIds": [item["span_id"] for item in originals],
                    "mappingType": mapping_type,
                    "outputKind": output_kind,
                    "exactness": mapping["exactness"],
                    "obligationIds": mapping["obligation_ids"],
                    "relationIds": mapping["relation_ids"],
                    "sourceLabels": [
                        mapping["reason_code"],
                        f"{mapping['transform_component']}@{mapping['transform_version']}",
                    ],
                }
            )
    fragments.sort(key=lambda item: (item["lineStart"], item["id"]))
    return list(source_spans.values()), fragments


def report_coverage(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return coverage(None, None, None, "protected source-map items", "No report emitted.")
    value = report["source_map_coverage"]
    return coverage(
        value["protected_items_with_valid_map"],
        value["protected_items"],
        None,
        "protected source-map items",
        "Independent verification report.",
    )


def certificate_data(result: Any, tokenizer: str) -> dict[str, Any]:
    candidate = result.certificate.model_dump(mode="json") if result.certificate else None
    report = (
        result.verification_report.model_dump(mode="json") if result.verification_report else None
    )
    compact = (
        result.compact_verification_report.model_dump(mode="json")
        if result.compact_verification_report
        else None
    )
    if report is None:
        return {
            "status": "not_run",
            "identity": {
                "sourceHash": None,
                "normalizedSourceHash": None,
                "compressedArtifactHash": None,
                "certificateHash": None,
                "queryHash": None,
                "tokenizerIdentity": tokenizer,
                "componentVersions": {},
            },
            "obligations": coverage(
                None, None, None, "discovered obligations", "No certificate emitted."
            ),
            "relations": [],
            "sourceMap": report_coverage(None),
            "rules": [],
            "failedInvariants": [item.code for item in result.failed_invariants],
            "trustBoundary": [
                "Compressor proposes.",
                "Verifier checks.",
                "Unsafe compression is not emitted.",
            ],
            "note": "Incompressible result; full source retained at the protected mandatory floor.",
        }
    obligations = report["obligation_results"]
    discovered = sum(item["discovered"] for item in obligations.values())
    verified = sum(item["verified"] for item in obligations.values())
    rules = []
    for rule_id, value in obligations.items():
        status = "not_applicable"
        if value["applicability"] == "applicable":
            status = "verified" if value["discovered"] == value["verified"] else "failed"
        rules.append(
            {
                "id": rule_id,
                "severity": "hard",
                "status": status,
                "expected": f"{value['discovered']} discovered obligations",
                "observed": f"{value['verified']} independently verified",
                "evidenceSpanIds": [],
                "recommendation": "None." if status != "failed" else report["recommended_action"],
            }
        )
    relations = [
        {
            "className": item["class_name"],
            "discovered": item["discovered"],
            "verified": item["verified"],
            "status": "not_applicable"
            if item["discovered"] == 0
            else ("passed" if item["discovered"] == item["verified"] else "failed"),
            "relationIds": item["failed_relation_ids"],
        }
        for item in report["relation_results"]
    ]
    inner = candidate["certificate"] if candidate else {}
    return {
        "status": report["status"],
        "identity": {
            "sourceHash": report["verified_source_hash"],
            "normalizedSourceHash": report["verified_normalized_hash"],
            "compressedArtifactHash": report["verified_compressed_artifact_hash"],
            "certificateHash": candidate["certificate_hash"] if candidate else None,
            "queryHash": report["verified_query_hash"],
            "tokenizerIdentity": tokenizer,
            "componentVersions": inner.get("component_versions", {}),
        },
        "obligations": coverage(
            verified,
            discovered,
            None,
            "discovered obligations",
            "Independent verification report.",
        ),
        "relations": relations,
        "sourceMap": report_coverage(report),
        "rules": rules,
        "failedInvariants": [item.code for item in result.failed_invariants],
        "trustBoundary": [
            "Compressor proposes.",
            "Certificate records.",
            "Verifier recomputes.",
            "Recovery repairs.",
        ],
        "note": (
            "Machine-verifiable structural preservation evidence. "
            f"Compact verifier: {compact['status'] if compact else 'not run'}. "
            "This does not prove semantic equivalence."
        ),
    }


def scenario(
    item: dict[str, Any],
    scenario_id: str,
    label: str,
    description: str,
    generated: str,
) -> dict[str, Any]:
    tokenizer = resolve_tokenizer("tiktoken", "cl100k_base")
    registry = TokenizerRegistry()
    registry.register(tokenizer)
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind=item["source_kind"],
            authority="ui-static-export",
            media_type="application/json" if item["source_kind"] == "json" else "text/plain",
            text=item["context"],
        )
    )
    result = compress_with_cprgc(
        source,
        registry,
        tokenizer_identity=tokenizer.identity,
        query=item["question"],
        mode="target",
        run_id=deterministic_run_id(f"tracefold-ui:{item['item_id']}"),
        maximum_attempts=3,
    )
    final = result.final_result or result.raw_result
    source_map = final.source_map.model_dump(mode="json") if final.source_map else None
    is_incompressible = result.status.value == "incompressible"
    context = item["context"] if is_incompressible else result.context
    source_spans, fragments = actual_lineage(item["context"], context, source_map)
    tokenizer_name = tokenizer_label(tokenizer.identity.model_dump(mode="json"))
    final_reduction = None if is_incompressible else float(result.diagnostics.final_reduction)
    certificate = certificate_data(result, tokenizer_name)
    return {
        "id": scenario_id,
        "label": label,
        "shortLabel": label,
        "description": description,
        "source": {
            "id": item["source_id"],
            "label": f"{item['source_kind']} / {item['item_id']}",
            "kind": item["source_kind"],
            "text": item["context"],
            "hash": sha256_text(item["context"]),
            "generatedFrom": "reports/runs/phase9-gemini-primary/benchmark-items.jsonl",
        },
        "compactContext": context,
        "compactFragments": fragments,
        "sourceSpans": source_spans,
        "sourceMap": {
            "available": bool(fragments),
            "coverage": certificate["sourceMap"],
            "mappings": fragments,
            "note": (
                "Actual source-map records from the local TraceFold compiler."
                if fragments
                else "Detailed mappings were not emitted for this incompressible result."
            ),
        },
        "result": {
            "status": result.status.value,
            "finalAction": result.final_action.value,
            "originalSize": size(
                "original", item["context"], result.diagnostics.original_tokens, tokenizer_name
            ),
            "rawCompressedSize": size(
                "raw_compressed",
                context,
                result.diagnostics.raw_compressed_tokens,
                tokenizer_name,
            ),
            "finalRepairedSize": size(
                "final_repaired", context, result.diagnostics.final_tokens, tokenizer_name
            ),
            "requestedReduction": metric(
                float(result.diagnostics.requested_reduction), "raw", tokenizer_name
            ),
            "rawReduction": metric(
                float(result.diagnostics.raw_reduction)
                if result.diagnostics.raw_reduction is not None
                else None,
                "raw",
                tokenizer_name,
            ),
            "finalReduction": metric(final_reduction, "final", tokenizer_name),
            "certificateStatus": certificate["status"],
            "verificationStatus": certificate["status"],
            "tokenizerIdentity": tokenizer_name,
            "warnings": result.warnings,
            "synthetic": False,
        },
        "certificate": certificate,
        "recovery": None,
        "query": item["question"],
        "mode": "target",
        "generatedFromCommit": generated,
        "fixtureIdentity": f"{item['item_id']} / local cprgc_target",
        "evidenceScope": (
            "Deterministic local compiler run over a committed Phase 9 benchmark item; "
            "no target-model inference."
        ),
        "valuesSynthetic": False,
        "targetModelInference": False,
    }


def parse_triage(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    current: list[str] = []
    for line_value in path.read_text(encoding="utf-8").splitlines():
        if line_value.startswith("- `cpb-"):
            if current:
                findings.append(triage_finding(" ".join(current)))
            current = [line_value[2:]]
        elif current and line_value.startswith("  "):
            current.append(line_value.strip())
        elif current and line_value.startswith("-"):
            findings.append(triage_finding(" ".join(current)))
            current = []
    if current:
        findings.append(triage_finding(" ".join(current)))
    return findings


def triage_finding(text: str) -> dict[str, str]:
    match = re.match(r"`([^`]+)`:.*?Class: ([^.]+)\.\s*(.*)", text)
    if match is None:
        raise ValueError(f"unrecognized claim-freeze triage item: {text}")
    return {"itemId": match.group(1), "category": match.group(2), "summary": match.group(3)}


def benchmark(summary: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    methods = summary["scoring"]["methods"]
    full = methods["full_context"]
    cprgc = methods["cprgc_target"]
    reductions = {
        kind: metric(
            float(value), "final", tokenizer_label(summary["configured_tokenizer_identity"])
        )
        for kind, value in summary["structural_reduction_by_kind"].items()
    }
    per_source = {
        kind: {
            "correct": value["paired_correct"],
            "denominator": value["paired_denominator_full_correct"],
        }
        for kind, value in cprgc["per_kind"].items()
    }
    return {
        "benchmarkVersion": summary["benchmark_version"],
        "generatedFromCommit": manifest["benchmark_runner_commit"],
        "fixtureIdentity": "reports/runs/phase9-gemini-primary/summary.json + claim-freeze.md",
        "metricSource": "configured_tokenizer",
        "evidenceScope": "Committed sanitized Phase 9 live paired evidence.",
        "valuesSynthetic": False,
        "targetModelInference": True,
        "itemCount": summary["item_count"],
        "sourceKindDistribution": summary["source_kind_counts"],
        "preparedMethodCount": len(summary["method_ids"]),
        "preparedMethods": [
            {
                "id": method_id,
                "label": method_id.replace("_", " "),
                "lossy": method_id != "full_context",
            }
            for method_id in summary["method_ids"]
        ],
        "expectedRequestCount": summary["expected_request_count"],
        "liveRequestCount": summary["live_request_count"],
        "tokenizerAccounting": "configured",
        "tokenizerIdentity": tokenizer_label(summary["configured_tokenizer_identity"]),
        "pricingStatus": "unset",
        "structuralReductionByKind": reductions,
        "downstreamRetention": {"status": "live_measured", "value": cprgc["paired_retention"]},
        "primaryGate": summary["primary_gate"],
        "infrastructureStatus": "ready"
        if summary["infrastructure_failure_count"] == 0
        else "degraded",
        "notes": [
            "Paired retention is benchmark- and model-specific.",
            "Structural verification does not prove semantic equivalence.",
        ],
        "futureMetrics": {
            "fullContextAccuracy": full["accuracy"],
            "cprgcAccuracy": cprgc["accuracy"],
            "pairedRetention": cprgc["paired_retention"],
            "perSourceRetention": {
                key: value["paired_retention"] for key, value in cprgc["per_kind"].items()
            },
            "baselineComparison": {},
            "compression": summary["configured_mean_context_reduction"],
            "latency": cprgc["latency_ms"]["end_to_end"]["median"],
            "cost": None,
            "failureCounts": {"infrastructure": summary["infrastructure_failure_count"]},
        },
        "liveEvidence": {
            "modelId": summary["model_id"],
            "successfulRequests": summary["live_request_count"]
            - summary["infrastructure_failure_count"],
            "infrastructureFailures": summary["infrastructure_failure_count"],
            "fullContext": {"correct": full["correct"], "denominator": full["denominator"]},
            "cprgc": {"correct": cprgc["correct"], "denominator": cprgc["denominator"]},
            "pairedRetention": {
                "correct": cprgc["paired_correct"],
                "denominator": cprgc["paired_denominator_full_correct"],
                "value": cprgc["paired_retention"],
                "wilsonLow": cprgc["paired_retention_wilson_95"][0],
                "wilsonHigh": cprgc["paired_retention_wilson_95"][1],
            },
            "perSourceRetention": per_source,
            "providerRequestInputReduction": cprgc["mean_provider_request_input_reduction"],
            "providerUsage": {
                "fullInput": full["provider_input_tokens"],
                "cprgcInput": cprgc["provider_input_tokens"],
                "fullOutput": full["provider_output_tokens"],
                "cprgcOutput": cprgc["provider_output_tokens"],
            },
            "emittedContextReduction": summary["configured_mean_emitted_context_reduction"],
            "fallbackAdjustedReduction": summary["configured_mean_context_reduction"],
            "failureTriage": parse_triage(PRIMARY / "claim-freeze.md"),
        },
    }


def architecture() -> list[dict[str, Any]]:
    return [
        {
            "id": "source",
            "label": "Source",
            "input": "Source text + query",
            "output": "Bound source",
            "responsibility": "Accept exact source and authority.",
            "trustDomain": "compressor",
            "failureBehavior": "Reject malformed input or retain full context.",
        },
        {
            "id": "obligations",
            "label": "Obligation discovery",
            "input": "Bound source",
            "output": "Protected facts",
            "responsibility": "Discover mandatory evidence.",
            "trustDomain": "compressor",
            "failureBehavior": "Unknown discovery remains unknown.",
        },
        {
            "id": "relations",
            "label": "Relation extraction",
            "input": "Protected facts",
            "output": "Evidence edges",
            "responsibility": "Preserve required relationships.",
            "trustDomain": "compressor",
            "failureBehavior": "Unsafe omissions block emission.",
        },
        {
            "id": "context-ir",
            "label": "ContextIR",
            "input": "Facts + relations",
            "output": "Typed IR",
            "responsibility": "Bind evidence to source spans.",
            "trustDomain": "compressor",
            "failureBehavior": "Reject dangling references.",
        },
        {
            "id": "cprgc",
            "label": "CPRGC compiler",
            "input": "IR + budget",
            "output": "Compact context",
            "responsibility": "Compile minimum sufficient graph.",
            "trustDomain": "compressor",
            "failureBehavior": "Return incompressible when mandatory closure exceeds budget.",
        },
        {
            "id": "compact",
            "label": "Compact artifact",
            "input": "Selected graph",
            "output": "Source-mapped text",
            "responsibility": "Emit exact facts and relation bridges.",
            "trustDomain": "compressor",
            "failureBehavior": "Synthesized markers cannot satisfy exact obligations.",
        },
        {
            "id": "certificate",
            "label": "Certificate",
            "input": "Candidate + claims",
            "output": "Bound candidate",
            "responsibility": "Record hashes, coverage, and tokenizer.",
            "trustDomain": "compressor",
            "failureBehavior": "Candidate remains untrusted until verification.",
        },
        {
            "id": "verifier",
            "label": "Independent verifier",
            "input": "Source + candidate",
            "output": "Recomputed report",
            "responsibility": "Recompute structural invariants.",
            "trustDomain": "verifier",
            "failureBehavior": "Report failure without trusting compressor flags.",
        },
        {
            "id": "recovery",
            "label": "Recovery",
            "input": "Failed report",
            "output": "Safe final artifact",
            "responsibility": "Restore, expand, or fall back.",
            "trustDomain": "recovery",
            "failureBehavior": "Fallback reports zero final savings.",
        },
        {
            "id": "target",
            "label": "Target evaluation",
            "input": "Full and compact contexts",
            "output": "Paired evidence",
            "responsibility": "Measure answer retention separately.",
            "trustDomain": "target_evaluation",
            "failureBehavior": "Infrastructure failures remain separate.",
        },
    ]


def main() -> None:
    summary = read_json(PRIMARY / "summary.json")
    manifest = read_json(PRIMARY / "run-manifest.json")
    primary_hash_manifest = (PRIMARY / "artifact-hashes.json").read_text(encoding="utf-8")
    smoke_hash_manifest = (SMOKE / "artifact-hashes.json").read_text(encoding="utf-8")
    items = {item["item_id"]: item for item in read_jsonl(PRIMARY / "benchmark-items.jsonl")}
    generated = manifest["compiler_commit"]
    scenarios = [
        scenario(
            items["cpb-document-01"],
            "verified-target",
            "Verified document compression",
            (
                "Local target-mode compression with actual certificate, verifier report, "
                "and source map."
            ),
            generated,
        ),
        scenario(
            items["cpb-python-01"],
            "aggressive-incompressible",
            "Incompressible at protected mandatory floor",
            "TraceFold retained the full Python source rather than remove protected code evidence.",
            generated,
        ),
        scenario(
            items["cpb-logs-01"],
            "recovery-fallback",
            "Verified log compression",
            "Local target-mode log compression with actual event and trace mappings.",
            generated,
        ),
        scenario(
            items["cpb-json-01"],
            "prepared-benchmark",
            "Verified JSON compression",
            (
                "Local target-mode JSON compression; benchmark metrics remain sourced from "
                "frozen live evidence."
            ),
            generated,
        ),
    ]
    bundle = {
        "schemaVersion": "ui-demo-v1",
        "generatedAt": "2000-01-01T00:00:00Z",
        "generatedFromCommit": generated,
        "mode": "static_demo",
        "scenarios": scenarios,
        "benchmark": benchmark(summary, manifest),
        "architecture": architecture(),
        "limitations": [
            (
                "Static compression scenarios are deterministic local compiler runs; "
                "they make no target-model request."
            ),
            "Live paired evidence is frozen under reports/runs/phase9-gemini-primary/.",
            "Python is incompressible at its protected mandatory floor.",
            f"Primary evidence hash manifest: {sha256_text(primary_hash_manifest)}",
            f"Smoke evidence hash manifest: {sha256_text(smoke_hash_manifest)}",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")
    print(f"generated_from_commit={generated}")


if __name__ == "__main__":
    main()
