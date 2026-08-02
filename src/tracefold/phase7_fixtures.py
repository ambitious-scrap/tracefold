"""Deterministic ContextProofBench v1 and ControlledContextStress v1 items."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from tracefold.extractors import extract_obligations
from tracefold.hashing import hash_query, sha256_domain
from tracefold.phase6_fixtures import long_fixture_inputs
from tracefold.schemas.api import QueryEnvelope
from tracefold.schemas.common import HashDomain
from tracefold.schemas.phase2 import ContentType, ExtractionResult, SourceArtifact
from tracefold.schemas.phase7 import AnswerKey, AnswerType, BenchmarkItem, EvidenceSpan
from tracefold.sources import ingest_source

FIXTURE_TO_KIND = {
    "document": ContentType.DOCUMENT,
    "dialogue": ContentType.DIALOGUE,
    "json": ContentType.JSON,
    "logs": ContentType.LOG,
    "python": ContentType.PYTHON,
}


def fixture_sources() -> dict[str, SourceArtifact]:
    return {name: ingest_source(item) for name, item in long_fixture_inputs().items()}


def _extractions(sources: dict[str, SourceArtifact]) -> dict[str, ExtractionResult]:
    result: dict[str, ExtractionResult] = {}
    for name, source in sources.items():
        if name == "dense":
            continue
        result[name] = extract_obligations(source, FIXTURE_TO_KIND[name])
    return result


def _span(
    source: SourceArtifact, item_id: str, needle: str, index: int, label: str
) -> EvidenceSpan:
    text = source.raw_bytes.decode("utf-8")
    start = text.find(needle)
    if start < 0:
        raise ValueError(f"fixture evidence not found: {needle}")
    return EvidenceSpan(
        span_id=f"{item_id}:span:{index:02d}",
        source_id=source.source_id,
        char_start=start,
        char_end=start + len(needle),
        label=label,
        text_hash=sha256_domain(HashDomain.SPAN, needle.encode("utf-8")),
    )


def _ids(
    extraction: ExtractionResult,
    classes: Iterable[str],
    relation_types: Iterable[str],
) -> tuple[list[str], list[str]]:
    class_set = set(classes)
    relation_set = set(relation_types)
    obligations = sorted(
        item.obligation_id for item in extraction.obligations if item.class_name in class_set
    )
    relations = sorted(
        item.relation_id for item in extraction.relations if item.relation_type in relation_set
    )
    return obligations, relations


def _item(
    *,
    source_name: str,
    source: SourceArtifact,
    extraction: ExtractionResult,
    number: int,
    question: str,
    answer_key: AnswerKey,
    needles: list[tuple[str, str]],
    classes: Iterable[str] = (),
    relation_types: Iterable[str] = (),
    task_family: str,
    difficulty: Literal["easy", "medium", "hard"] = "medium",
    benchmark_version: str = "ContextProofBench-v1",
    notes: str = "",
) -> BenchmarkItem:
    item_id = (
        f"cpb-{source_name}-{number:02d}"
        if benchmark_version.startswith("ContextProof")
        else (f"ccs-{source_name}-{number:02d}")
    )
    spans = [
        _span(source, item_id, needle, index, label)
        for index, (needle, label) in enumerate(needles)
    ]
    obligation_ids, relation_ids = _ids(extraction, classes, relation_types)
    return BenchmarkItem(
        benchmark_version=benchmark_version,
        item_id=item_id,
        source_kind=FIXTURE_TO_KIND[source_name],
        source_id=source.source_id,
        context=source.raw_bytes.decode("utf-8"),
        question=question,
        answer_key=answer_key,
        supporting_spans=spans,
        protected_obligation_ids=obligation_ids,
        required_relation_ids=relation_ids,
        difficulty=difficulty,
        task_family=task_family,
        query_hash=hash_query(QueryEnvelope(query=question)),
        notes=notes,
    )


def _number(value: str, unit: str | None = None) -> AnswerKey:
    return AnswerKey(
        answer_type=AnswerType.NUMBER_WITH_UNIT if unit else AnswerType.NUMBER,
        accepted_answers=[value],
        exact_numeric_answer=value,
        required_units=[unit] if unit else [],
    )


def _text(
    value: str,
    *,
    kind: AnswerType = AnswerType.EXACT_STRING,
    json_path: str | None = None,
) -> AnswerKey:
    return AnswerKey(answer_type=kind, accepted_answers=[value], json_path=json_path)


def _build_documents(source: SourceArtifact, extraction: ExtractionResult) -> list[BenchmarkItem]:
    return [
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=1,
            question="What timeout value is specified for gateway-api?",
            answer_key=_number("5000"),
            needles=[("timeout is 5000", "timeout"), ("gateway-api", "owner")],
            classes=["numeric.number"],
            relation_types=["relation.value_unit_owner"],
            task_family="numeric-constraint",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=2,
            question="What unit is attached to the gateway-api timeout?",
            answer_key=_text("ms", kind=AnswerType.CATEGORICAL),
            needles=[("5000 ms", "value-unit")],
            classes=["numeric.unit"],
            relation_types=["relation.value_unit_owner"],
            task_family="unit",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=3,
            question="What active version is recorded for gateway-api?",
            answer_key=_text("v2.7.4", kind=AnswerType.IDENTIFIER),
            needles=[("active version is v2.7.4", "version")],
            classes=["identifier.version"],
            task_family="version",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=4,
            question="What action does the release rule prohibit?",
            answer_key=_text("external transfer", kind=AnswerType.CATEGORICAL),
            needles=[("external transfer is prohibited", "prohibition")],
            classes=["policy.prohibition"],
            relation_types=["relation.rule_exception"],
            task_family="prohibition",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=5,
            question="What exact approval condition permits external transfer?",
            answer_key=_text("owner_approval = true", kind=AnswerType.EXACT_STRING),
            needles=[("owner_approval = true", "condition")],
            classes=["logic.condition", "policy.permission"],
            relation_types=["relation.rule_exception"],
            task_family="exception",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=6,
            question="Which ticket permits the signed package during scheduled maintenance?",
            answer_key=_text("REQ-8842", kind=AnswerType.IDENTIFIER),
            needles=[("ticket=REQ-8842", "ticket"), ("signed package", "package")],
            classes=["identifier.generic", "logic.exception"],
            task_family="exception",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=7,
            question="How many failed health checks start rollback?",
            answer_key=_number("3"),
            needles=[("3 failed health checks", "rollback threshold")],
            classes=["numeric.number", "logic.condition"],
            relation_types=["relation.condition_consequence"],
            task_family="condition",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=8,
            question="What date is attached to the rollback evidence?",
            answer_key=AnswerKey(answer_type=AnswerType.DATE, accepted_answers=["2026-08-01"]),
            needles=[("2026-08-01", "date")],
            classes=["temporal.date"],
            task_family="date",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=9,
            question="What begins after three failed health checks?",
            answer_key=_text("rollback begins", kind=AnswerType.SHORT_FREE_TEXT),
            needles=[("rollback begins after 3 failed health checks", "consequence")],
            classes=["logic.condition"],
            relation_types=["relation.condition_consequence"],
            task_family="condition",
        ),
        _item(
            source_name="document",
            source=source,
            extraction=extraction,
            number=10,
            question="What do teams record before and after ordinary maintenance?",
            answer_key=_text("the same checklist", kind=AnswerType.SHORT_FREE_TEXT),
            needles=[
                ("same checklist before and after ordinary maintenance", "maintenance checklist")
            ],
            classes=["instruction.system_developer"],
            task_family="boilerplate-retrieval",
        ),
    ]


def _build_dialogue(source: SourceArtifact, extraction: ExtractionResult) -> list[BenchmarkItem]:
    return [
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=1,
            question="What ticket is named in the active request?",
            answer_key=_text("REQ-8842", kind=AnswerType.IDENTIFIER),
            needles=[("Active request: explain why ticket=REQ-8842", "active request")],
            classes=["identifier.generic", "role.boundary"],
            task_family="latest-request",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=2,
            question="Which service supersedes worker-api in the correction?",
            answer_key=_text("gateway-api", kind=AnswerType.IDENTIFIER),
            needles=[("Correction: use gateway-api, not worker-api", "correction")],
            classes=["temporal.correction"],
            relation_types=["relation.statement_correction"],
            task_family="correction",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=3,
            question="Which earlier service is rejected by the correction?",
            answer_key=_text("worker-api", kind=AnswerType.IDENTIFIER),
            needles=[("not worker-api", "superseded service")],
            classes=["temporal.correction"],
            relation_types=["relation.statement_correction"],
            task_family="correction",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=4,
            question="What corrected timeout value is requested?",
            answer_key=_number("5000", "ms"),
            needles=[("5000 ms timeout", "corrected timeout")],
            classes=["numeric.number", "numeric.unit"],
            task_family="numeric-constraint",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=5,
            question="Who owns the corrected timeout?",
            answer_key=_text("owner", kind=AnswerType.CATEGORICAL),
            needles=[("timeout owner", "owner")],
            classes=["entity.named", "numeric.unit"],
            relation_types=["relation.value_unit_owner"],
            task_family="ownership",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=6,
            question="What exact condition governs the commitment not to transfer data?",
            answer_key=_text("owner_approval = true"),
            needles=[("not transfer data unless owner_approval = true", "commitment")],
            classes=["dialogue.commitment", "policy.prohibition", "logic.condition"],
            task_family="commitment",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=7,
            question="What must the system preserve according to the system message?",
            answer_key=_text("exact identifiers", kind=AnswerType.SHORT_FREE_TEXT),
            needles=[
                (
                    "system: Follow change-control policy and preserve exact identifiers",
                    "system constraint",
                )
            ],
            classes=["instruction.system_developer", "role.boundary"],
            relation_types=["relation.instruction_scope"],
            task_family="system-constraint",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=8,
            question="Which three fields must operational decisions contain?",
            answer_key=_text("owner, scope, and exception", kind=AnswerType.SHORT_FREE_TEXT),
            needles=[
                (
                    "Return operational decisions with owner, scope, and exception",
                    "developer constraint",
                )
            ],
            classes=["instruction.system_developer", "role.boundary"],
            relation_types=["relation.instruction_scope"],
            task_family="developer-constraint",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=9,
            question="What does the assistant commit to record before proceeding?",
            answer_key=_text(
                "checklist, owner, rollback window, and audit event",
                kind=AnswerType.SHORT_FREE_TEXT,
            ),
            needles=[
                (
                    "I will record the checklist, owner, rollback window, and audit event",
                    "commitment",
                )
            ],
            classes=["dialogue.commitment"],
            task_family="commitment",
        ),
        _item(
            source_name="dialogue",
            source=source,
            extraction=extraction,
            number=10,
            question="What did the tool report about routine planning output?",
            answer_key=_text("no new anomaly found", kind=AnswerType.SHORT_FREE_TEXT),
            needles=[("no new anomaly was found in routine planning output", "tool result")],
            classes=["role.boundary"],
            task_family="tool-result",
        ),
    ]


def _build_json(source: SourceArtifact, extraction: ExtractionResult) -> list[BenchmarkItem]:
    return [
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=1,
            question="What is the status of the anomalous record with trace-json-053?",
            answer_key=_text("error", kind=AnswerType.CATEGORICAL),
            needles=[('"status":"error"', "anomaly status"), ('"trace-json-053"', "trace id")],
            classes=["structured.anomalous_row"],
            task_family="anomaly",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=2,
            question="What latency value is recorded for trace-json-053?",
            answer_key=_number("9000", "ms"),
            needles=[('"latency_ms":9000', "anomaly latency"), ('"trace-json-053"', "trace id")],
            classes=["numeric.number", "structured.anomalous_row"],
            task_family="identifier-lookup",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=3,
            question="What exact trace identifier is attached to the anomalous row?",
            answer_key=_text("trace-json-053", kind=AnswerType.IDENTIFIER),
            needles=[("trace-json-053", "trace identifier")],
            classes=["identifier.trace_request", "structured.anomalous_row"],
            task_family="identifier-lookup",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=4,
            question="How many records does the response declare?",
            answer_key=_number("72"),
            needles=[('"total":72', "total")],
            classes=["numeric.number", "structured.json_schema_path"],
            task_family="exact-aggregation",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=5,
            question="What schema version does the response declare?",
            answer_key=_text("v2.7.4", kind=AnswerType.IDENTIFIER),
            needles=[('"schema_version":"v2.7.4"', "schema version")],
            classes=["identifier.version", "structured.json_schema_path"],
            task_family="schema",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=6,
            question="What is the maximum latency_ms value in the records?",
            answer_key=_number("9000", "ms"),
            needles=[('"latency_ms":9000', "maximum latency")],
            classes=["numeric.number", "structured.anomalous_row"],
            task_family="extrema",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=7,
            question="What service owns trace-json-053?",
            answer_key=_text("gateway-api", kind=AnswerType.IDENTIFIER),
            needles=[('"service":"gateway-api"', "service"), ("trace-json-053", "trace")],
            classes=["entity.named", "identifier.trace_request"],
            task_family="ownership",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=8,
            question="Which field is explicitly null in the first record?",
            answer_key=_text(
                "trace_id", kind=AnswerType.JSON_FIELD, json_path="records[0].trace_id"
            ),
            needles=[('"trace_id":null', "explicit null")],
            classes=["structured.json_schema_path"],
            task_family="null-vs-value",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=9,
            question="Which region appears on the anomalous record?",
            answer_key=_text("ap-south-1", kind=AnswerType.CATEGORICAL),
            needles=[('"region":"ap-south-1"', "anomaly region"), ("trace-json-053", "trace")],
            classes=["entity.named", "structured.anomalous_row"],
            task_family="nested-path",
        ),
        _item(
            source_name="json",
            source=source,
            extraction=extraction,
            number=10,
            question="What owner is recorded for the response records?",
            answer_key=_text("platform", kind=AnswerType.CATEGORICAL),
            needles=[('"owner":"platform"', "owner")],
            classes=["entity.named"],
            relation_types=["relation.value_unit_owner"],
            task_family="categorical-count",
        ),
    ]


def _build_logs(source: SourceArtifact, extraction: ExtractionResult) -> list[BenchmarkItem]:
    return [
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=1,
            question="What error code appears first in the rare failure trace?",
            answer_key=_text("E42", kind=AnswerType.IDENTIFIER),
            needles=[("error_code=E42", "first error")],
            classes=["log.severity_change"],
            relation_types=["relation.event_trace"],
            task_family="error-code",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=2,
            question="What error code appears after predecessor E41?",
            answer_key=_text("E43", kind=AnswerType.IDENTIFIER),
            needles=[("predecessor=E41 error_code=E43", "causal error")],
            classes=["log.severity_change"],
            relation_types=["relation.error_causal_predecessor"],
            task_family="causal-predecessor",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=3,
            question="What trace ID links the rare error events?",
            answer_key=_text("trace-rare", kind=AnswerType.IDENTIFIER),
            needles=[("trace=trace-rare", "trace id")],
            classes=["identifier.trace_request"],
            relation_types=["relation.event_trace"],
            task_family="trace-link",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=4,
            question="What request ID links the rare error events?",
            answer_key=_text("REQ-77", kind=AnswerType.IDENTIFIER),
            needles=[("request_id=REQ-77", "request id")],
            classes=["identifier.trace_request"],
            relation_types=["relation.event_trace"],
            task_family="request-link",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=5,
            question="What service emitted the rare error chain?",
            answer_key=_text("auth", kind=AnswerType.IDENTIFIER),
            needles=[("service=auth error_code=E42", "service")],
            classes=["entity.named"],
            task_family="service-identity",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=6,
            question="At what timestamp did the first ERROR occur?",
            answer_key=AnswerKey(
                answer_type=AnswerType.DATE, accepted_answers=["2026-08-01T09:00:01"]
            ),
            needles=[("2026-08-01T09:00:01 ERROR", "first error time")],
            classes=["temporal.timestamp"],
            relation_types=["relation.event_timestamp"],
            task_family="timestamp",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=7,
            question="How many normal INFO health-check events precede the warning?",
            answer_key=_number("120"),
            needles=[
                ("2026-08-01T00:00:00 INFO", "first normal"),
                ("2026-08-01T00:01:59 INFO", "last normal"),
            ],
            classes=["temporal.timestamp"],
            task_family="exact-aggregation",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=8,
            question="What status follows the rare error chain during recovery?",
            answer_key=_text("ok", kind=AnswerType.CATEGORICAL),
            needles=[("recovery status=ok", "recovery")],
            classes=["log.severity_change"],
            task_family="severity-transition",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=9,
            question="What status did the warning introduce before the errors?",
            answer_key=_text("degraded", kind=AnswerType.CATEGORICAL),
            needles=[("WARN service=auth health-check status=degraded", "warning transition")],
            classes=["log.severity_change"],
            task_family="severity-transition",
        ),
        _item(
            source_name="logs",
            source=source,
            extraction=extraction,
            number=10,
            question="Which predecessor code is attached to error E43?",
            answer_key=_text("E41", kind=AnswerType.IDENTIFIER),
            needles=[("predecessor=E41", "predecessor")],
            classes=["log.severity_change"],
            relation_types=["relation.error_causal_predecessor"],
            task_family="causal-predecessor",
        ),
    ]


def _build_python(source: SourceArtifact, extraction: ExtractionResult) -> list[BenchmarkItem]:
    return [
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=1,
            question="What is the name of the protected transfer function?",
            answer_key=_text("transfer", kind=AnswerType.CODE_SYMBOL),
            needles=[("def transfer(store, owner_approval, attempts):", "transfer signature")],
            classes=["code.definition"],
            relation_types=["relation.definition_use"],
            task_family="function-signature",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=2,
            question="What guard controls external transfer?",
            answer_key=_text("if not owner_approval", kind=AnswerType.CODE_SYMBOL),
            needles=[("if not owner_approval:", "branch guard")],
            classes=["code.branch_guard"],
            task_family="branch-guard",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=3,
            question="Which exception is raised when owner approval is absent?",
            answer_key=_text("PermissionError", kind=AnswerType.CODE_SYMBOL),
            needles=[("raise PermissionError", "permission exception")],
            classes=["code.exception_path"],
            task_family="exception-path",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=4,
            question="Which exception is raised when attempts reach the retry limit?",
            answer_key=_text("RuntimeError", kind=AnswerType.CODE_SYMBOL),
            needles=[("raise RuntimeError", "retry exception")],
            classes=["code.exception_path"],
            task_family="exception-path",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=5,
            question="What is the MAX_RETRIES constant?",
            answer_key=_number("3"),
            needles=[("MAX_RETRIES = 3", "retry constant")],
            classes=["code.constant"],
            task_family="constant",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=6,
            question="Which function calls transfer with request fields?",
            answer_key=_text("handle", kind=AnswerType.CODE_SYMBOL),
            needles=[
                ("def handle(store, request):", "caller"),
                ("return transfer(store, request.owner_approval", "callee"),
            ],
            classes=["code.definition", "code.call"],
            relation_types=["relation.caller_callee"],
            task_family="caller-callee",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=7,
            question="Which imported symbol comes from dataclasses?",
            answer_key=_text("dataclass", kind=AnswerType.CODE_SYMBOL),
            needles=[("from dataclasses import dataclass", "import")],
            classes=["code.import", "code.definition"],
            relation_types=["relation.import_symbol"],
            task_family="import",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=8,
            question="What call executes after both transfer guards pass?",
            answer_key=_text("store.send()", kind=AnswerType.CODE_SYMBOL),
            needles=[("return store.send()", "return call")],
            classes=["code.call"],
            task_family="return-behavior",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=9,
            question="What public function is repeated in the repository packet?",
            answer_key=_text("list_records_0", kind=AnswerType.CODE_SYMBOL),
            needles=[("def list_records_0():", "public function")],
            classes=["code.definition"],
            task_family="public-api",
        ),
        _item(
            source_name="python",
            source=source,
            extraction=extraction,
            number=10,
            question="What argument supplies approval to transfer?",
            answer_key=_text("request.owner_approval", kind=AnswerType.CODE_SYMBOL),
            needles=[("request.owner_approval", "owner argument")],
            classes=["code.call"],
            relation_types=["relation.caller_callee"],
            task_family="caller-callee",
        ),
    ]


def build_context_proof_bench() -> tuple[BenchmarkItem, ...]:
    sources = fixture_sources()
    extraction = _extractions(sources)
    items = (
        _build_documents(sources["document"], extraction["document"])
        + _build_dialogue(sources["dialogue"], extraction["dialogue"])
        + _build_json(sources["json"], extraction["json"])
        + _build_logs(sources["logs"], extraction["logs"])
        + _build_python(sources["python"], extraction["python"])
    )
    if len(items) != 50 or len({item.item_id for item in items}) != 50:
        raise ValueError("ContextProofBench v1 must contain 50 unique items")
    return tuple(items)


def build_controlled_context_stress() -> tuple[BenchmarkItem, ...]:
    sources = fixture_sources()
    extraction = _extractions(sources)
    source = sources["document"]
    result: list[BenchmarkItem] = []
    tasks = [
        (
            "needle",
            "What ticket is the signed package exception bound to?",
            _text("REQ-8842", kind=AnswerType.IDENTIFIER),
            [("REQ-8842", "needle")],
        ),
        (
            "multiple-key",
            "What are the gateway version and timeout?",
            _text("v2.7.4; 5000 ms", kind=AnswerType.SHORT_FREE_TEXT),
            [("v2.7.4", "version"), ("5000 ms", "timeout")],
        ),
        (
            "ordered-event",
            "What is the order of rollback evidence, exception, and release rule?",
            _text("release rule; exception; rollback evidence", kind=AnswerType.ORDERED_LIST),
            [
                ("Release rule", "rule"),
                ("Exception:", "exception"),
                ("Question-critical evidence", "rollback"),
            ],
        ),
        (
            "aggregation",
            "How many failed health checks trigger rollback?",
            _number("3"),
            [("3 failed health checks", "count")],
        ),
        (
            "recency",
            "What is the latest active service request in the document?",
            _text("gateway-api", kind=AnswerType.IDENTIFIER),
            [("gateway-api", "service")],
        ),
        (
            "relation-bridge",
            "Which approval condition is connected to external transfer?",
            _text("owner_approval = true"),
            [("external transfer is prohibited", "rule"), ("owner_approval = true", "condition")],
        ),
        (
            "attribution",
            "Which source subsection contains the rollback threshold?",
            _text("Question-critical evidence", kind=AnswerType.CATEGORICAL),
            [("Question-critical evidence", "subsection")],
        ),
        (
            "distractor-identifier",
            "What exact ticket identifier must be used?",
            _text("REQ-8842", kind=AnswerType.IDENTIFIER),
            [("ticket=REQ-8842", "identifier")],
        ),
    ]
    for number, (family, question, key, needles) in enumerate(tasks, 1):
        result.append(
            _item(
                source_name="document",
                source=source,
                extraction=extraction["document"],
                number=number,
                question=question,
                answer_key=key,
                needles=needles,
                classes=["identifier.generic", "logic.condition"],
                relation_types=["relation.rule_exception"],
                difficulty="hard",
                task_family=family,
                benchmark_version="ControlledContextStress-v1",
            )
        )
    return tuple(result)


__all__ = ["build_context_proof_bench", "build_controlled_context_stress", "fixture_sources"]
