"""Deterministic, plausible high-redundancy Phase 6 fixture inputs."""

from __future__ import annotations

import json

from tracefold.schemas.source import SourceInput


def long_document() -> str:
    boilerplate = (
        "The operations handbook describes routine deployment review, ownership, "
        "rollback preparation, notification, and audit logging for every service. "
        "Teams record the same checklist before and after ordinary maintenance.\n"
    )
    sections = [boilerplate * 3 for _ in range(16)]
    protected = (
        "Release rule: external transfer is prohibited unless owner_approval = true. "
        "The timeout is 5000 ms for gateway-api and the active version is v2.7.4.\n"
        "Exception: scheduled maintenance may transfer a signed package when ticket=REQ-8842.\n"
        "Question-critical evidence: rollback begins after 3 failed health checks on 2026-08-01.\n"
    )
    return (
        "# Deployment Operations Handbook\n"
        + "\n".join(sections)
        + protected
        + "\n"
        + boilerplate * 4
    )


def long_dialogue() -> str:
    turns: list[str] = [
        "system: Follow change-control policy and preserve exact identifiers.",
        "developer: Return operational decisions with owner, scope, and exception.",
    ]
    for index in range(25):
        turns.extend(
            [
                (
                    f"user: Planning pass {index} repeats the same migration checklist "
                    "and review notes for the platform team."
                ),
                (
                    "assistant: I will record the checklist, owner, rollback window, "
                    "and audit event before proceeding."
                ),
                (
                    "tool: migration metadata loaded; no new anomaly was found in "
                    "routine planning output."
                ),
            ]
        )
    turns.extend(
        [
            "user: Correction: use gateway-api, not worker-api, for the 5000 ms timeout owner.",
            "assistant: Commitment: I will not transfer data unless owner_approval = true.",
            (
                "user: Active request: explain why ticket=REQ-8842 permits the "
                "signed maintenance package."
            ),
        ]
    )
    return "\n".join(turns) + "\n"


def large_json() -> str:
    rows: list[dict[str, object]] = []
    for index in range(72):
        rows.append(
            {
                "service": "gateway-api",
                "region": "ap-south-1" if index % 5 == 0 else "us-east-1",
                "status": "ok",
                "latency_ms": 42,
                "owner": "platform",
                "trace_id": None,
                "optional_note": None if index % 7 == 0 else "steady",
            }
        )
    rows[53] = {
        "service": "gateway-api",
        "region": "ap-south-1",
        "status": "error",
        "latency_ms": 9000,
        "owner": "platform",
        "trace_id": "trace-json-053",
        "optional_note": None,
    }
    return json.dumps(
        {"records": rows, "total": len(rows), "schema_version": "v2.7.4"}, separators=(",", ":")
    )


def repetitive_logs() -> str:
    lines = [
        f"2026-08-01T00:{index // 60:02d}:{index % 60:02d} INFO service=auth health-check status=ok"
        for index in range(120)
    ]
    lines.extend(
        [
            ("2026-08-01T09:00:00 WARN service=auth health-check status=degraded trace=trace-rare"),
            (
                "2026-08-01T09:00:01 ERROR service=auth error_code=E42 "
                "trace=trace-rare request_id=REQ-77"
            ),
            (
                "2026-08-01T09:00:02 ERROR service=auth predecessor=E41 error_code=E43 "
                "trace=trace-rare request_id=REQ-77"
            ),
            (
                "2026-08-01T09:00:03 INFO service=auth recovery status=ok "
                "trace=trace-rare request_id=REQ-77"
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def python_packet() -> str:
    functions = []
    for index in range(32):
        functions.append(
            f"def list_records_{index}():\n"
            f'    """CRUD list_records operation {index}."""\n'
            "    pass\n"
        )
    packet_notes = 'packet_notes = """\n'
    packet_notes += (
        """Repository packet: migration storage service API.
Public list operations return active records in source order.
Create operations validate owner and tenant before persistence.
Update operations use optimistic revision checks and preserve audit fields.
Delete operations are soft deletes; recovery jobs retain tombstones.
Read paths use bounded retries around the repository adapter.
Transport failures are classified before retry budget is consumed.
Permission failures are never retried as transient transport errors.
Request handlers attach trace identifiers to every repository call.
Metrics distinguish cache hits, database reads, and queue handoffs.
Schema migrations run before workers advertise readiness.
Backfills checkpoint after each partition and resume from exact offsets.
Service shutdown drains writes before closing the connection pool.
Health checks report dependency state without exposing credentials.
Administrative endpoints require owner approval and change tickets.
Retention jobs redact personal fields before archival export.
The packet includes public symbols plus one protected transfer path.
Repository adapters expose idempotent create and update operations.
List pagination uses opaque cursors; callers must not infer row offsets.
Write batches carry a request identifier through storage and audit sinks.
Validation errors include field paths while transport errors include retry class.
Workers use bounded concurrency and release leases on every exit path.
Queue consumers acknowledge messages only after durable state commits.
Read replicas may lag; authoritative checks use the primary connection.
Feature flags are scoped by tenant and default to the documented safe value.
Configuration reloads validate the complete snapshot before publication.
Audit records include actor, action, resource, request, and timestamp fields.
Export jobs preserve stable column order and represent absent values distinctly.
Incident tooling correlates errors by trace and request identifiers.
Operational runbooks distinguish rollback, roll-forward, and data repair.
The packet is intentionally verbose around repeated public repository contracts.
Service ownership is explicit at module, endpoint, and persisted-record scope.
Release verification checks source identity before any migration is applied.
Data repair commands require dry-run output, approval, and a bounded row count.
Repository tests cover empty pages, duplicate requests, stale revisions, and retries.
The public packet omits implementation secrets while retaining interface contracts.
Deployment records include version, environment, owner, ticket, and rollback status.
Recovery procedures capture operator, reason, source revision, and verification report.
Public interfaces reject unknown fields rather than silently dropping client intent.
Repository packets retain enough context to trace ownership across service boundaries.
The protected transfer function supplies guard, exception, and caller evidence.
Repository clients use explicit timeouts and surface cancellation to callers.
Batch boundaries are stable so replay can identify the first failed record.
Database errors retain vendor code, operation, and transaction state.
Queue retries use backoff classes rather than unbounded immediate polling.
Cache invalidation follows successful writes and records the affected key.
Tenant isolation checks happen before authorization-dependent field selection.
Service handlers avoid logging payload values that contain credentials.
Read models document nullable fields and distinguish missing from explicit null.
Migration runners record checksum, source revision, and completion timestamp.
Operator actions are auditable and link to the original change request.
Public API examples preserve exact status codes and pagination semantics.
Failure responses identify safe retry behavior without leaking internal paths.
Repository health evidence includes dependency name, state, and observation time.
The repeated contracts provide realistic soft context around protected code.
"""
        + '"""\n\n'
    )

    critical = (
        "\nMAX_RETRIES = 3\n"
        "def transfer(store, owner_approval, attempts):\n"
        "    if not owner_approval:\n"
        "        raise PermissionError('external transfer prohibited')\n"
        "    if attempts >= MAX_RETRIES:\n"
        "        raise RuntimeError('circuit breaker')\n"
        "    return store.send()\n"
        "\ndef handle(store, request):\n"
        "    return transfer(store, request.owner_approval, request.attempts)\n"
    )
    imports = "from dataclasses import dataclass\nimport math\n\n"
    return imports + packet_notes + "\n".join(functions) + critical


def dense_incompressible() -> str:
    lines = []
    for index in range(38):
        lines.append(
            f"Rule {index}: owner=user-{index:03d} value={index * 7919 + 17} ms "
            f"trace=trace-dense-{index:03d} exception=case-{index:03d} "
            f"condition=region-{index:03d} correction=revision-{index:03d}."
        )
    return "\n".join(lines) + "\n"


def long_fixture_inputs() -> dict[str, SourceInput]:
    return {
        "document": SourceInput(
            input_ordinal=0,
            kind="document",
            authority="phase6-fixture",
            media_type="text/plain",
            text=long_document(),
        ),
        "dialogue": SourceInput(
            input_ordinal=1,
            kind="dialogue",
            authority="phase6-fixture",
            media_type="text/plain",
            text=long_dialogue(),
        ),
        "json": SourceInput(
            input_ordinal=2,
            kind="json",
            authority="phase6-fixture",
            media_type="application/json",
            text=large_json(),
        ),
        "logs": SourceInput(
            input_ordinal=3,
            kind="log",
            authority="phase6-fixture",
            media_type="text/plain",
            text=repetitive_logs(),
        ),
        "python": SourceInput(
            input_ordinal=4,
            kind="python",
            authority="phase6-fixture",
            media_type="text/x-python",
            file_path="phase6/packet.py",
            text=python_packet(),
        ),
        "dense": SourceInput(
            input_ordinal=5,
            kind="document",
            authority="phase6-fixture",
            media_type="text/plain",
            text=dense_incompressible(),
        ),
    }


__all__ = [
    "dense_incompressible",
    "large_json",
    "long_dialogue",
    "long_document",
    "long_fixture_inputs",
    "python_packet",
    "repetitive_logs",
]
