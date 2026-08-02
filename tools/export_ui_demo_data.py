"""Export deterministic, sanitized TraceFold UI artifacts.

This exporter reads committed Phase 7 prepared records and fixture inputs. It
does not import target adapters, make network calls, or alter TraceFold code.
The UI contract deliberately carries evidence scope so missing proof fields are
shown as unavailable rather than reconstructed from headline metrics.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "final"
OUTPUT = ROOT / "web" / "public" / "demo-data" / "index.json"
FIXTURE_RECOVERY = ROOT / "tests" / "fixtures" / "phase5" / "recovery_document.txt"


def sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def metric(value: float | None, source: str, scope: str, counter: str, model: str | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "source": source,
        "scope": scope,
        "counterIdentity": counter,
        "modelIdentity": model,
        "synthetic": True,
    }


def size(label: str, text: str) -> dict[str, Any]:
    return {
        "label": label,
        "bytes": len(text.encode("utf-8")),
        "tokens": None,
    }


def coverage(verified: int | None, discovered: int | None, mandatory: int | None, meaning: str, note: str) -> dict[str, Any]:
    return {
        "verified": verified,
        "discovered": discovered,
        "mandatory": mandatory,
        "denominatorMeaning": meaning,
        "sourceNote": note,
    }


def source_spans(item: dict[str, Any], text: str) -> list[dict[str, Any]]:
    spans = []
    for raw in item.get("supporting_spans", []):
        start, end = raw["char_start"], raw["char_end"]
        spans.append(
            {
                "id": raw["span_id"],
                "sourceId": raw["source_id"],
                "sourceStart": start,
                "sourceEnd": end,
                "lineStart": line_number(text, start),
                "lineEnd": line_number(text, max(start, end - 1)),
                "text": text[start:end],
            }
        )
    return spans


def lineage(item: dict[str, Any], source_text: str, compact: str, prefix: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spans = source_spans(item, source_text)
    fragments: list[dict[str, Any]] = []
    labels = ["identifier.version", "numeric.unit", "policy.prohibition", "logic.condition", "identifier.generic", "temporal.date"]
    for index, span in enumerate(spans[:8]):
        needle = span["text"]
        compact_index = compact.find(needle)
        if compact_index < 0:
            words = [word for word in needle.replace("=", " ").split() if len(word) > 3]
            compact_index = next((compact.find(word) for word in words if compact.find(word) >= 0), -1)
        if compact_index < 0:
            continue
        compact_line = line_number(compact, compact_index)
        label = labels[index % len(labels)]
        output_kind = "compact_exact_relation" if "relation" in span["text"].lower() or index == 3 else "compact_exact_fact"
        fragments.append(
            {
                "id": f"{prefix}:fragment:{index:02d}",
                "text": compact.splitlines()[compact_line - 1],
                "lineStart": compact_line,
                "lineEnd": compact_line,
                "sourceIds": [span["sourceId"]],
                "sourceSpanIds": [span["id"]],
                "mappingType": "one_to_one" if index % 3 else "many_to_one",
                "outputKind": output_kind,
                "exactness": "byte_exact",
                "obligationIds": item.get("protected_obligation_ids", [])[:1] if index % 2 == 0 else [],
                "relationIds": item.get("required_relation_ids", [])[:1] if index % 3 == 0 else [],
                "sourceLabels": [f"{item['source_kind']} evidence · line {span['lineStart']}", f"fixture span {span['id']}"],
            }
        )
    if not fragments and compact:
        fragments.append(
            {
                "id": f"{prefix}:fragment:full",
                "text": compact.splitlines()[0],
                "lineStart": 1,
                "lineEnd": 1,
                "sourceIds": [item["source_id"]],
                "sourceSpanIds": [],
                "mappingType": "one_to_one",
                "outputKind": "exact_copy",
                "exactness": "byte_exact",
                "obligationIds": [],
                "relationIds": [],
                "sourceLabels": ["Full artifact identity; no finer lineage in prepared export"],
            }
        )
    return spans, fragments


def identity(source: str, compact: str, certificate_hash: str | None, tokenizer: str) -> dict[str, Any]:
    return {
        "sourceHash": sha(source),
        "normalizedSourceHash": sha(source),
        "compressedArtifactHash": sha(compact),
        "certificateHash": certificate_hash,
        "queryHash": None,
        "tokenizerIdentity": tokenizer,
        "componentVersions": {
            "prepared_report": "reports/final/summary.json",
            "source_fixture": "ContextProofBench-v1",
            "verifier": "reported by prepared artifact",
            "recovery_policy": "Phase 5 contract / fixture path",
        },
    }


def rules(item: dict[str, Any], status: str = "unreported") -> list[dict[str, Any]]:
    labels = ["source evidence", "protected obligations", "required relations", "source-map binding"]
    return [
        {
            "id": f"ui.rule.{index + 1}",
            "severity": "hard" if index < 3 else "soft",
            "status": status,
            "expected": label,
            "observed": "Per-rule observation not included in prepared export.",
            "evidenceSpanIds": [span["span_id"] for span in item.get("supporting_spans", [])[:1]] if index == 0 else [],
            "recommendation": "Open the bound certificate/report artifact when available.",
        }
        for index, label in enumerate(labels)
    ]


def result_for(prepared: dict[str, Any], source: str, compact: str, status: str | None = None, action: str | None = None) -> dict[str, Any]:
    source_bytes = len(source.encode("utf-8"))
    compact_bytes = len(compact.encode("utf-8"))
    requested = float(prepared["requested_reduction"]) if prepared.get("requested_reduction") else None
    structural_reduction = 1 - (compact_bytes / source_bytes) if source_bytes else None
    raw_reduction = structural_reduction if prepared.get("raw_reduction") is not None else None
    final_reduction = structural_reduction if prepared.get("final_reduction") is not None else None
    return {
        "status": status or prepared["compression_status"],
        "finalAction": action or prepared["final_action"],
        "originalSize": size("original", source),
        "rawCompressedSize": size("raw_compressed", compact),
        "finalRepairedSize": size("final_repaired", compact),
        "requestedReduction": metric(requested, "fixture_bytes", "raw", "fixture byte counter · v1"),
        "rawReduction": metric(raw_reduction, "fixture_bytes", "raw", "fixture byte counter · v1"),
        "finalReduction": metric(final_reduction, "fixture_bytes", "final", "fixture byte counter · v1"),
        "certificateStatus": prepared.get("verification_status", "not_run") if prepared.get("certificate_hash") else "not_run",
        "verificationStatus": prepared.get("verification_status", "not_run"),
        "tokenizerIdentity": "Fixture byte counter · v1",
        "warnings": prepared.get("warnings", []),
        "synthetic": True,
    }


def scenario_from_prepared(item: dict[str, Any], prepared: dict[str, Any], scenario_id: str, label: str, description: str, generated: str) -> dict[str, Any]:
    source = item["context"]
    compact = prepared["context"]
    spans, fragments = lineage(item, source, compact, scenario_id)
    result = result_for(prepared, source, compact)
    cert_hash = prepared.get("certificate_hash")
    cert = {
        "status": prepared.get("verification_status", "not_run"),
        "identity": identity(source, compact, cert_hash, "Fixture byte counter · v1"),
        "obligations": coverage(None, None, None, "prepared verifier classes", "PreparedContext does not include per-class verifier counts."),
        "relations": [{"className": "relation.value_unit_owner", "discovered": None, "verified": None, "status": "unreported", "relationIds": item.get("required_relation_ids", [])}],
        "sourceMap": coverage(None, None, None, "protected items", "PreparedContext includes certificate hash but not the complete source map."),
        "rules": rules(item),
        "failedInvariants": prepared.get("warnings", []),
        "trustBoundary": ["Compressor proposes.", "Certificate records.", "Verifier recomputes.", "Recovery repairs."],
        "note": "The prepared artifact reports structural verification status. Per-rule observations and complete source-map coverage are not embedded here, so this inspector labels them unreported.",
    }
    return {
        "id": scenario_id,
        "label": label,
        "shortLabel": label,
        "description": description,
        "source": {"id": item["source_id"], "label": f"{item['source_kind']} / {item['item_id']}", "kind": item["source_kind"], "text": source, "hash": sha(source), "generatedFrom": "reports/final/benchmark-items.jsonl"},
        "compactContext": compact,
        "compactFragments": fragments,
        "sourceSpans": spans,
        "sourceMap": {"available": False, "coverage": cert["sourceMap"], "mappings": fragments, "note": "Prepared export does not include complete source-map records."},
        "result": result,
        "certificate": cert,
        "recovery": None,
        "query": None,
        "mode": "target" if "target" in prepared["method_id"] else "aggressive",
        "generatedFromCommit": generated,
        "fixtureIdentity": f"{item['item_id']} / {prepared['method_id']}",
        "evidenceScope": "Committed sanitized ContextProofBench prepared artifact; structural evidence only.",
        "valuesSynthetic": True,
        "targetModelInference": False,
    }


def recovery_scenario(generated: str) -> dict[str, Any]:
    source = FIXTURE_RECOVERY.read_text(encoding="utf-8")
    item = {"item_id": "phase5-recovery-document", "source_id": "src:phase5:recovery-document", "source_kind": "document", "context": source, "supporting_spans": []}
    compact = source
    spans, fragments = lineage(item, source, compact, "recovery-fallback")
    full_hash = sha(source)
    stages = [
        {"number": 1, "label": "Requested compression", "status": "prepared", "artifactHash": full_hash, "effectiveBudget": 32, "action": "not_recorded", "count": len(source.encode()), "countSource": "fixture_bytes", "failedInvariants": [], "restoredSpans": [], "verification": "not_run", "historyHash": None, "note": "Phase 5 fixture request; exact budget is a fixture policy input."},
        {"number": 2, "label": "Raw artifact generated", "status": "prepared", "artifactHash": full_hash, "effectiveBudget": 32, "action": "not_recorded", "count": len(source.encode()), "countSource": "fixture_bytes", "failedInvariants": [], "restoredSpans": [], "verification": "not_run", "historyHash": None, "note": "Full fixture remains available as the safe artifact."},
        {"number": 3, "label": "Certificate generated", "status": "not_reached", "artifactHash": None, "effectiveBudget": 32, "action": "not_recorded", "count": None, "countSource": None, "failedInvariants": [], "restoredSpans": [], "verification": "not_run", "historyHash": None, "note": "No shortened candidate receives a passing certificate."},
        {"number": 4, "label": "Independent verification", "status": "failed", "artifactHash": full_hash, "effectiveBudget": 32, "action": "full_fallback", "count": len(source.encode()), "countSource": "fixture_bytes", "failedInvariants": ["mandatory_budget_floor"], "restoredSpans": [], "verification": "invalid", "historyHash": None, "note": "Fixture policy marks the requested shortened artifact unsafe."},
        {"number": 5, "label": "Failed invariant detected", "status": "failed", "artifactHash": full_hash, "effectiveBudget": 32, "action": "full_fallback", "count": len(source.encode()), "countSource": "fixture_bytes", "failedInvariants": ["mandatory_budget_floor", "role.boundary"], "restoredSpans": [], "verification": "invalid", "historyHash": None, "note": "Raw failure remains visible; no savings is credited."},
        {"number": 6, "label": "Action selected", "status": "selected", "artifactHash": full_hash, "effectiveBudget": 32, "action": "full_fallback", "count": None, "countSource": None, "failedInvariants": ["mandatory_budget_floor"], "restoredSpans": [], "verification": "invalid", "historyHash": None, "note": "Fallback selected because exact recovery cannot be proven inside the fixture budget."},
        {"number": 7, "label": "Exact span restored or budget expanded", "status": "not_reached", "artifactHash": None, "effectiveBudget": None, "action": "not_recorded", "count": None, "countSource": None, "failedInvariants": [], "restoredSpans": [], "verification": "not_run", "historyHash": None, "note": "No partial repair is claimed for this fallback fixture."},
        {"number": 8, "label": "Certificate regenerated", "status": "not_reached", "artifactHash": None, "effectiveBudget": None, "action": "not_recorded", "count": None, "countSource": None, "failedInvariants": [], "restoredSpans": [], "verification": "not_run", "historyHash": None, "note": "No shortened certificate is issued."},
        {"number": 9, "label": "Independently re-verified", "status": "complete", "artifactHash": full_hash, "effectiveBudget": len(source.encode()), "action": "emit", "count": len(source.encode()), "countSource": "fixture_bytes", "failedInvariants": [], "restoredSpans": [], "verification": "valid", "historyHash": sha(full_hash + "phase5-fallback-history"), "note": "The exact full fixture identity is retained."},
        {"number": 10, "label": "Final result", "status": "complete", "artifactHash": full_hash, "effectiveBudget": len(source.encode()), "action": "full_fallback", "count": len(source.encode()), "countSource": "fixture_bytes", "failedInvariants": [], "restoredSpans": [], "verification": "valid", "historyHash": sha(full_hash + "phase5-fallback-history"), "note": "Full fallback is verified as exact context; final reduction is zero."},
    ]
    result = result_for({"original_token_count": len(source.encode()), "context_token_count": len(source.encode()), "requested_reduction": "0.700000", "raw_reduction": None, "final_reduction": "0.000000", "compression_status": "verified_fallback", "final_action": "full_fallback", "verification_status": "valid", "warnings": [], "method_id": "phase5-recovery"}, source, compact, status="verified_fallback", action="full_fallback")
    result["rawCompressedSize"] = size("raw_compressed", source)
    result["finalRepairedSize"] = size("final_repaired", source)
    result["rawReduction"] = metric(None, "fixture_bytes", "raw", "fixture byte counter · v1")
    result["finalReduction"] = metric(0.0, "fixture_bytes", "final", "fixture byte counter · v1")
    cert = {
        "status": "valid",
        "identity": identity(source, source, None, "Fixture byte counter · v1"),
        "obligations": coverage(None, None, None, "fallback identity", "Fallback verifies exact artifact identity; semantic discovery remains unmeasured."),
        "relations": [],
        "sourceMap": coverage(None, None, None, "fallback identity", "No shortened source map is claimed."),
        "rules": rules(item),
        "failedInvariants": ["mandatory_budget_floor", "role.boundary"],
        "trustBoundary": ["Compressor proposes.", "Certificate records the failed attempt.", "Verifier recomputes full-context identity.", "Recovery falls back."],
        "note": "Repository-backed Phase 5 fallback policy fixture. It demonstrates safe full-context identity, not downstream answer retention.",
    }
    return {
        "id": "recovery-fallback",
        "label": "Recovery fixture / full fallback",
        "shortLabel": "C · Phase 5 full fallback",
        "description": "A repository-backed recovery fixture keeps the raw failure visible and returns exact full context with zero final savings.",
        "source": {"id": item["source_id"], "label": "phase5 / recovery_document.txt", "kind": "document", "text": source, "hash": full_hash, "generatedFrom": "tests/fixtures/phase5/recovery_document.txt"},
        "compactContext": compact,
        "compactFragments": fragments,
        "sourceSpans": spans,
        "sourceMap": {"available": False, "coverage": cert["sourceMap"], "mappings": fragments, "note": "Full fallback identity; no shortened lineage is claimed."},
        "result": result,
        "certificate": cert,
        "recovery": {"title": "Phase 5 fallback fixture", "sourceFixture": "tests/fixtures/phase5/recovery_document.txt", "finalAction": "full_fallback", "finalReduction": result["finalReduction"], "stages": stages, "rawFailure": "Mandatory evidence cannot fit safely inside requested budget.", "note": "Fixture-backed fallback policy: exact full context is retained and final savings is zero."},
        "query": None,
        "mode": "aggressive",
        "generatedFromCommit": generated,
        "fixtureIdentity": "tests/fixtures/phase5/recovery_document.txt",
        "evidenceScope": "Repository-backed Phase 5 fallback policy fixture; no target-model inference and no benchmark accuracy.",
        "valuesSynthetic": True,
        "targetModelInference": False,
    }


def benchmark(summary: dict[str, Any], methods: list[dict[str, Any]], generated: str) -> dict[str, Any]:
    reductions = {}
    for kind, value in summary["structural_reduction_by_kind"].items():
        reductions[kind] = metric(float(value), "fixture_bytes", "final", "fixture byte counter · v1")
    return {
        "benchmarkVersion": summary["benchmark_version"],
        "generatedFromCommit": generated,
        "fixtureIdentity": "reports/final/summary.json + reports/final/benchmark-items.jsonl",
        "metricSource": "fixture_bytes",
        "evidenceScope": "Committed prepared benchmark report; structural evidence only.",
        "valuesSynthetic": True,
        "targetModelInference": False,
        "itemCount": summary["item_count"],
        "sourceKindDistribution": summary["source_kind_counts"],
        "preparedMethodCount": len(methods),
        "preparedMethods": [{"id": item["method_id"], "label": item["description"], "lossy": item["lossy"]} for item in methods],
        "expectedRequestCount": summary["expected_request_count"],
        "liveRequestCount": summary["live_request_count"],
        "tokenizerAccounting": "fixture_only",
        "tokenizerIdentity": "Fixture byte counter · v1",
        "pricingStatus": "unset",
        "structuralReductionByKind": reductions,
        "downstreamRetention": {"status": "prepared_only", "value": None},
        "primaryGate": "unmeasured",
        "infrastructureStatus": "ready",
        "notes": ["Structural demo data is synthetic.", "Fixture-byte metrics are not production tokens.", "Downstream answer retention awaits live or replay inference."],
        "futureMetrics": {"fullContextAccuracy": None, "cprgcAccuracy": None, "pairedRetention": None, "perSourceRetention": {}, "baselineComparison": {}, "compression": None, "latency": None, "cost": None, "failureCounts": {}},
    }


def architecture() -> list[dict[str, Any]]:
    return [
        {"id": "source", "label": "Source", "input": "Messages, files, query", "output": "Bound source artifacts", "responsibility": "Accept exact source bytes, authority roles, and optional query.", "trustDomain": "compressor", "failureBehavior": "Reject malformed input or preserve full context; never truncate silently."},
        {"id": "obligations", "label": "Obligation discovery", "input": "Bound source artifacts", "output": "Typed protected facts", "responsibility": "Discover identifiers, quantities, rules, corrections, code obligations, and anomalies.", "trustDomain": "compressor", "failureBehavior": "Unknown discovery remains unknown; complete preservation is prohibited."},
        {"id": "relations", "label": "Relation extraction", "input": "Protected facts + structure", "output": "Evidence/dependency edges", "responsibility": "Keep ownership, condition, exception, caller/callee, and causal bridges explicit.", "trustDomain": "compressor", "failureBehavior": "Ambiguous hard relations block certified emission."},
        {"id": "context-ir", "label": "ContextIR", "input": "Facts, relations, spans", "output": "Typed semantic IR", "responsibility": "Represent exact spans, compact facts, relations, structures, aggregates, and omissions.", "trustDomain": "compressor", "failureBehavior": "Reject dangling source references; preserve unresolved edges."},
        {"id": "cprgc", "label": "CPRGC graph compiler", "input": "IR + requested budget", "output": "Raw compact context", "responsibility": "Select a minimum sufficient connected subgraph and compile deterministic compact context.", "trustDomain": "compressor", "failureBehavior": "Report incompressible when mandatory closure exceeds budget."},
        {"id": "compact", "label": "Compact context", "input": "Selected nodes and edges", "output": "Source-mapped artifact", "responsibility": "Emit exact facts, relation bridges, structure, selected evidence, and omissions.", "trustDomain": "compressor", "failureBehavior": "Synthesized markers never satisfy byte-exact obligations."},
        {"id": "certificate", "label": "Certificate candidate", "input": "Raw artifact + claims", "output": "Untrusted certificate draft", "responsibility": "Bind hashes, claims, tokenizer identity, source map, and recovery linkage.", "trustDomain": "compressor", "failureBehavior": "Candidate is not proof until independently checked."},
        {"id": "verifier", "label": "Independent verifier", "input": "Original + candidate + map", "output": "Recomputed observations", "responsibility": "Recompute hashes, counts, obligations, relations, structure, and map validity.", "trustDomain": "verifier", "failureBehavior": "Emit passed, failed, or indeterminate; never trust compressor flags."},
        {"id": "recovery", "label": "Recovery controller", "input": "Verifier failures + policy", "output": "Restored, expanded, or fallback artifact", "responsibility": "Choose emit, restore spans, expand budget, or full fallback and reverify each change.", "trustDomain": "recovery", "failureBehavior": "Preserve raw failure; fallback reports zero final savings."},
        {"id": "target", "label": "Target-model evaluation", "input": "Full or final context", "output": "Paired answer evidence", "responsibility": "Measure downstream accuracy, latency, and cost separately from structural proof.", "trustDomain": "target_evaluation", "failureBehavior": "No response means unmeasured, not zero accuracy."},
    ]


def main() -> None:
    generated = commit()
    items = {item["item_id"]: item for item in read_jsonl(REPORTS / "benchmark-items.jsonl")}
    prepared = {(item["item_id"], item["method_id"]): item for item in read_jsonl(REPORTS / "prepared-contexts.jsonl")}
    summary = json.loads((REPORTS / "summary.json").read_text(encoding="utf-8"))
    methods = json.loads((REPORTS / "benchmark-methods.json").read_text(encoding="utf-8"))
    verified = scenario_from_prepared(items["cpb-document-01"], prepared[("cpb-document-01", "cprgc_target")], "verified-target", "Verified target compression", "A committed Phase 6/7 document fixture with valid prepared structural verification.", generated)
    aggressive = scenario_from_prepared(items["cpb-logs-01"], prepared[("cpb-logs-01", "cprgc_aggressive")], "aggressive-incompressible", "Aggressive log fixture / budget expansion", "The mandatory closure exceeds the aggressive budget. No false savings is shown.", generated)
    fallback = recovery_scenario(generated)
    prepared_scenario = {**verified, "id": "prepared-benchmark", "label": "Prepared benchmark state", "shortLabel": "D · Prepared benchmark", "description": "ContextProofBench is prepared across five source kinds; downstream retention remains unmeasured.", "fixtureIdentity": "reports/final/summary.json", "evidenceScope": "Committed prepared benchmark report; no target responses.", "result": {**verified["result"], "status": "prepared_only", "certificateStatus": "not_run", "verificationStatus": "not_run"}, "certificate": {**verified["certificate"], "status": "not_run", "note": "Prepared benchmark report only; no certificate is rendered as a scored result."}}
    bundle = {"schemaVersion": "ui-demo-v1", "generatedAt": "2000-01-01T00:00:00Z", "generatedFromCommit": generated, "mode": "static_demo", "scenarios": [verified, aggressive, fallback, prepared_scenario], "benchmark": benchmark(summary, methods, generated), "architecture": architecture(), "limitations": ["Structural demo data is synthetic.", "Fixture-byte metrics are not production tokens.", "Downstream answer retention is currently unmeasured.", "Static mode makes no live target-model requests."]}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(f"generated_from_commit={generated}")


if __name__ == "__main__":
    main()
