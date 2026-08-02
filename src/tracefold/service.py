"""Shared runnable compression surface for CLI and HTTP API."""

from __future__ import annotations

import hashlib
import uuid

from tracefold.cprgc import compress_with_cprgc
from tracefold.schemas.phase7r import (
    PublicCompressionRequest,
    PublicCompressionResponse,
    RecoverySummary,
    SourceMapSummary,
)
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source
from tracefold.tokenizers import TokenizerRegistry, resolve_tokenizer


def _run_id(request: PublicCompressionRequest) -> str:
    digest = bytearray(hashlib.sha256(request.model_dump_json().encode()).digest()[:16])
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(digest)))


def compress_public(request: PublicCompressionRequest) -> PublicCompressionResponse:
    tokenizer = resolve_tokenizer(request.tokenizer_backend, request.tokenizer_encoding)
    registry = TokenizerRegistry()
    registry.register(tokenizer)
    source = ingest_source(
        SourceInput(
            input_ordinal=0,
            kind=request.source_kind,
            authority="public-request",
            media_type=request.media_type,
            text=request.source_text,
            file_path=request.file_path,
        )
    )
    result = compress_with_cprgc(
        source,
        registry,
        tokenizer_identity=tokenizer.identity,
        query=request.query,
        mode=request.mode,
        target_token_budget=request.target_token_budget,
        run_id=_run_id(request),
        maximum_attempts=request.maximum_recovery_attempts,
        maximum_final_token_budget=request.maximum_final_budget,
    )
    final = result.final_result or result.raw_result
    source_map = final.source_map
    recovery = result.recovery_result
    return PublicCompressionResponse(
        run_id=result.raw_result.run_id,
        source_id=source.source_id,
        status=result.status,
        compressed_context=(
            request.source_text if result.status.value == "incompressible" else result.context
        ),
        tokenizer_identity=result.tokenizer_identity,
        original_tokens=result.diagnostics.original_tokens,
        raw_tokens=result.diagnostics.raw_compressed_tokens,
        final_tokens=result.diagnostics.final_tokens,
        raw_reduction=result.diagnostics.raw_reduction,
        final_reduction=result.diagnostics.final_reduction,
        final_action=result.final_action,
        certificate=(
            result.certificate.model_dump(mode="json") if result.certificate is not None else None
        ),
        verification_report=(
            result.verification_report.model_dump(mode="json")
            if result.verification_report is not None
            else None
        ),
        compact_verification_report=(
            result.compact_verification_report.model_dump(mode="json")
            if result.compact_verification_report is not None
            else None
        ),
        failed_invariants=result.failed_invariants,
        recovery=RecoverySummary(
            final_status=recovery.final_status if recovery is not None else None,
            final_action=result.final_action,
            attempt_count=len(recovery.attempts) if recovery is not None else 0,
            restored_token_count=result.diagnostics.restored_tokens,
        ),
        source_map=SourceMapSummary(
            map_id=source_map.map_id if source_map is not None else None,
            artifact_count=len(source_map.artifacts) if source_map is not None else 0,
            span_count=len(source_map.spans) if source_map is not None else 0,
            mapping_count=len(source_map.mappings) if source_map is not None else 0,
            omission_count=len(final.omitted_spans),
        ),
        warnings=result.warnings,
    )


__all__ = ["compress_public"]
