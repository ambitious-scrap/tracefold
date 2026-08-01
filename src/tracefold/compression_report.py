import base64
import json
from pathlib import Path

from tracefold.compression import compress_source
from tracefold.schemas.phase2 import ContentType
from tracefold.schemas.phase3 import RawCompressionRequest
from tracefold.schemas.source import SourceInput
from tracefold.sources import ingest_source
from tracefold.tokenizers import TokenizerIdentity, TokenizerRegistry


class _ReportTokenizer:
    """Deterministic non-production tokenizer for local Phase 3 diagnostics."""

    identity = TokenizerIdentity(
        implementation="fixture",
        identifier="fixture",
        revision="1",
        configuration_hash="sha256:" + "a" * 64,
    )

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def count(self, text: str) -> int:
        return len(self.encode(text))


def build_report() -> list[dict[str, object]]:
    root = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "phase3"
    fixtures = (
        ("document.txt", ContentType.DOCUMENT, 0.05),
        ("dialogue.txt", ContentType.DIALOGUE, 0.0),
        ("records.json", ContentType.JSON, 0.0),
        ("simple_records.json", ContentType.JSON, 0.25),
        ("events.log", ContentType.LOG, 0.03),
        ("phase3_example.py", ContentType.PYTHON, 0.0),
    )
    tokenizer = _ReportTokenizer()
    registry = TokenizerRegistry()
    registry.register(tokenizer)
    rows: list[dict[str, object]] = []
    for ordinal, (name, kind, reduction) in enumerate(fixtures):
        payload = (root / name).read_bytes()
        source = ingest_source(
            SourceInput(
                input_ordinal=ordinal,
                kind=kind.value,
                authority="fixture",
                media_type=("application/json" if kind == ContentType.JSON else "text/plain"),
                bytes_base64=base64.b64encode(payload).decode("ascii"),
            )
        )
        request = RawCompressionRequest(
            run_id="123e4567-e89b-42d3-a456-426614174000",
            source_id=source.source_id,
            source_kind=kind,
            tokenizer_id=tokenizer.identity,
            requested_reduction=reduction,
        )
        result = compress_source(request, source, registry)
        rows.append(
            {
                "fixture": name,
                "status": result.status.value,
                "original_tokens": result.original_token_count,
                "compressed_tokens": result.compressed_token_count,
                "achieved_reduction": result.achieved_reduction,
                "mandatory_token_floor": result.minimum_mandatory_token_count,
                "omitted_spans": len(result.omitted_spans),
            }
        )
    return rows


def main() -> None:
    print(json.dumps(build_report(), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
