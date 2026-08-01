from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

HashValue = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
Ratio = Annotated[str, StringConstraints(pattern=r"^(0|1)\.\d{6}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactStage(StrEnum):
    ORIGINAL = "original"
    NORMALIZED = "normalized"
    RAW_COMPRESSED = "raw_compressed"
    RESTORED = "restored"
    FINAL_COMPRESSED = "final_compressed"


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


class FinalAction(StrEnum):
    EMIT = "emit"
    RESTORE_SPANS = "restore_spans"
    EXPAND_BUDGET = "expand_budget"
    FULL_FALLBACK = "full_fallback"


class DiscoveryStatus(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class Completeness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class HashDomain(StrEnum):
    CERTIFICATE = "tracefold:certificate:1.0.0"
    SOURCE_MANIFEST = "tracefold:source-manifest:1"
    QUERY = "tracefold:query:1"
    COMPRESSION_REQUEST = "tracefold:compression-request:1"
    SOURCE_ARTIFACT = "tracefold:source-artifact:1"
    NORMALIZED_ARTIFACT = "tracefold:normalized-artifact:1"
    CONTEXT_ARTIFACT = "tracefold:context-artifact:1"
    SOURCE_MAP = "tracefold:source-map:1"
    SPAN = "tracefold:span:1"
    RECOVERY_EVENT = "tracefold:recovery-event:1"
    RECOVERY_HISTORY = "tracefold:recovery-history:1"


class TokenizerIdentity(StrictModel):
    implementation: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    configuration_hash: HashValue


class ComponentIdentity(StrictModel):
    component_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ParserWarning(StrictModel):
    source: Literal["compressor", "verifier"]
    component_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    source_ids: list[str]
    message: str = Field(min_length=1)


class FailedInvariant(StrictModel):
    invariant_id: str
    class_name: str
    kind: Literal["obligation", "relation", "hash", "source_map", "parser", "policy"]
    severity: Literal["hard", "soft"]
    code: str
    message: str
    source_span_ids: list[str]
    candidate_span_ids: list[str]
    recovery_hint: str
