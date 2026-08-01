# TraceFold Phase 1 Contract — Deterministic Project Scaffolding

Status: proposed next-phase contract; implementation not started

Phase contract version: `phase-1/1.0`

Source basis: the explicit Phase 1 scope in the Phase 0 task, `productSpec.md` §§11–14, and `buildPlan.md` §§4, 6.1, 9.1, 10, and 18. **[PROPOSED PROJECT DECISION]** The exact allowlist, package dependencies, interface signatures, route/CLI behavior, schema partition, and exit commands below are proposed project decisions; none is implemented in Phase 0.

## Objective

Create the smallest installable Python project that can represent, serialize, hash, validate, and expose TraceFold's frozen domain contracts without performing compression or semantic analysis.

Phase 1 proves that the contract is implementable and deterministic. It does not prove preservation and does not produce a certified compressed context.

## Scope

Phase 1 includes only:

- Python project scaffolding and package layout;
- Pydantic domain schemas corresponding to the Phase 0 contracts;
- canonical JSON serialization;
- domain-separated SHA-256 hashing utilities;
- tokenizer protocol, registry, and deterministic test tokenizer;
- CLI shell;
- FastAPI shell;
- structured logging and run IDs;
- deterministic non-benchmark test fixtures;
- one CI-ready test command.

## Files allowed to be created

**[PROPOSED PROJECT DECISION]** The implementation allowlist is exact. Phase 1 may create only these files:

```text
pyproject.toml
src/tracefold/__init__.py
src/tracefold/__main__.py
src/tracefold/api.py
src/tracefold/cli.py
src/tracefold/logging.py
src/tracefold/run_ids.py
src/tracefold/serialization.py
src/tracefold/hashing.py
src/tracefold/tokenizers/__init__.py
src/tracefold/tokenizers/base.py
src/tracefold/tokenizers/registry.py
src/tracefold/schemas/__init__.py
src/tracefold/schemas/common.py
src/tracefold/schemas/source.py
src/tracefold/schemas/source_map.py
src/tracefold/schemas/certificate.py
src/tracefold/schemas/api.py
tests/conftest.py
tests/test_api_shell.py
tests/test_certificate_schema.py
tests/test_cli_shell.py
tests/test_hashing.py
tests/test_run_ids_and_logging.py
tests/test_serialization.py
tests/test_source_map_schema.py
tests/test_tokenizers.py
tests/fixtures/canonical/query-null.json
tests/fixtures/canonical/query-text.json
tests/fixtures/canonical/source-manifest.json
tests/fixtures/canonical/certificate-synthetic.json
tests/fixtures/canonical/source-map-synthetic.json
```

Directories implied by those files may be created. Generated `*.egg-info`, cache, build, and coverage files are ignored artifacts, not phase outputs.

Phase 1 MUST NOT modify:

- `productSpec.md`;
- `buildPlan.md`;
- any Phase 0 contract document;
- `.gitignore`, unless a separately approved repository-maintenance change is made outside the phase commit.

No `apps/`, `benchmarks/`, `configs/`, `reports/`, frontend, model, analyzer, compiler, verifier, calibration, restoration, source-store, or adapter package is allowed in Phase 1.

## Package and dependency contract

- Python requirement: `>=3.11`.
- `src/` layout with import root `tracefold`.
- Runtime dependencies are limited to Pydantic v2, FastAPI, and Typer plus their transitive dependencies.
- Test dependencies are limited to pytest, HTTPX/TestClient support, and a formatting/lint tool only if its command is added to the exit gate in the same phase review.
- No ML, tokenizer-model, parser, database, benchmark, frontend, or hosted-API dependency is allowed.
- **[PROPOSED PROJECT DECISION]** `tracefold.__version__` starts at `0.1.0`; schema versions remain independently `1.0.0`.

Dependency ranges in `pyproject.toml` MUST constrain supported major versions. Exact resolved versions are recorded by CI/runtime metadata; introducing a lockfile is deferred because it is not in the file allowlist.

## Public interfaces

Only the interfaces below are public in Phase 1. Everything else is private.

### Serialization

```python
def canonical_json_bytes(value: object) -> bytes: ...
def canonical_json_text(value: object) -> str: ...
def parse_json_strict(data: bytes | str) -> object: ...
```

Rules:

- Implements the project RFC 8785 profile from `certificate-schema.md`.
- Rejects duplicate keys, invalid Unicode, NaN, infinities, and unsupported object types.
- Produces UTF-8 with no BOM and no trailing newline.
- Pydantic models serialize through their JSON-compatible representation with explicit `null` fields retained where required by schema.

### Hashing

```python
def sha256_domain(domain: str, payload: bytes) -> str: ...
def hash_canonical(domain: str, value: object) -> str: ...
def hash_query(query: QueryEnvelope) -> str: ...
def hash_source_manifest(manifest: SourceManifest) -> str: ...
```

Rules:

- Returns lowercase `sha256:<64 hex>`.
- Domain input is ASCII and implementation adds the required NUL separator exactly once.
- Query null and query empty string MUST hash differently.
- Hash utilities perform no I/O and never normalize payload bytes implicitly.

### Run IDs

```python
def new_run_id() -> str: ...
def validate_run_id(value: str) -> str: ...
```

**[PROPOSED PROJECT DECISION]** Production run IDs are lowercase RFC 4122 UUIDv4 strings. Tests inject fixed IDs; run IDs are correlation metadata, never artifact identity or proof.

### Logging

```python
def configure_logging(*, level: str = "INFO") -> None: ...
def bind_run_context(run_id: str, attempt_id: str | None = None): ...
```

Logs are structured, include run/attempt IDs when bound, and never include source/query/context/certificate payloads by default. Secret values are never logged. Logging has no import-time global configuration side effect.

### Tokenizer abstraction

```python
@runtime_checkable
class Tokenizer(Protocol):
    @property
    def identity(self) -> TokenizerIdentity: ...
    def encode(self, text: str) -> Sequence[int]: ...
    def count(self, text: str) -> int: ...

class TokenizerRegistry:
    def register(self, tokenizer: Tokenizer) -> None: ...
    def resolve(self, identity: TokenizerIdentity) -> Tokenizer: ...
```

Rules:

- Identity is implementation + identifier + immutable revision + configuration hash.
- Duplicate identity registration is rejected.
- Unknown identity raises a typed error; no implicit default or approximation.
- **[PROPOSED PROJECT DECISION]** Phase 1 includes only a deterministic fixture tokenizer in tests. No `tiktoken` or Hugging Face adapter is implemented yet.

### CLI shell

The executable name is `tracefold`; `python -m tracefold` is equivalent.

Allowed commands:

```text
tracefold --help
tracefold version
tracefold schema certificate --check
tracefold schema source-map --check
tracefold compress --help
tracefold serve --help
```

- `version` prints only the package version.
- `schema ... --check` loads the matching synthetic fixture, validates it, canonicalizes it twice, and exits without writing files.
- `compress --help` exists only to reserve the interface. Any actual invocation returns exit code `3`, stable error code `PHASE_1_NOT_IMPLEMENTED`, and no compressed context/certificate.
- `serve --help` documents how to import/run the FastAPI shell; it does not auto-start a background service in tests.

### FastAPI shell

Public application object:

```python
from tracefold.api import app
```

Allowed routes:

| Method/path | Behavior |
|---|---|
| `GET /healthz` | `200` with schema-valid `{status, service_version}`; no dependency/model checks. |
| `GET /version` | `200` with package and schema versions. |
| `POST /v1/compress` | Validates `CompressionRequest`, then returns `501` and stable `PHASE_1_NOT_IMPLEMENTED`; never returns a fabricated certificate. |

No target-model, compare, retrieve, explain, or certificate-verification route is implemented in Phase 1.

## Schemas

All models are Pydantic v2 models with `extra="forbid"`, strict field validation, deterministic serialization, and explicit enums.

### Common schemas

- `HashValue`: validated `sha256:<64 lowercase hex>` string type.
- `SemVer`: validated semantic-version string type used for schema/component versions.
- `ArtifactStage`: `original`, `normalized`, `raw_compressed`, `restored`, `final_compressed`.
- `VerificationStatus`: `passed`, `failed`, `indeterminate`.
- `FinalAction`: `emit`, `restore_spans`, `expand_budget`, `full_fallback`.
- `DiscoveryStatus`: `known`, `partial`, `unknown`.
- `Completeness`: `complete`, `partial`, `unknown`.
- `ParserWarning`, `FailedInvariant`, `ComponentIdentity`, `TokenizerIdentity`.

### Source schemas

- `SourceInput`: input ordinal, kind/authority, media type, portable path/message metadata, and exactly one payload form: UTF-8 `text` or base64-encoded raw `bytes_base64`.
- `SourceManifestEntry`: immutable stable source ID, input ordinal, kind/authority, media type, raw byte hash, byte length, and portable file path/message metadata; it never embeds source payload.
- `SourceManifest`: ordered non-empty list of `SourceManifestEntry` records; duplicate source IDs rejected.
- `QueryEnvelope`: required `query: str | None`; no omitted sentinel.
- `ArtifactIdentity`: artifact ID, stage, media type, encoding, lengths, hash, nullable typed location metadata.

Manifest/certificate schemas represent bytes by hash/length/reference. API input schemas carry exact caller content so a future implementation has an unambiguous request contract. Phase 1 validates that content but does not process or log it.

### Source-map schemas

- `SourceCoordinate`, `SourceSpan`, `MappingRecord`, `MapCoverage`, `SourceMap` exactly reflect `source-map-schema.md`.
- Validators enforce nonnegative half-open ranges, `start <= end`, matching coordinate availability, unique IDs, allowed transforms/exactness combinations, and forward/reverse index consistency.
- Phase 1 validation does not read artifacts or verify span byte hashes; that is future verifier behavior.

### Certificate schemas

- `HashClaimObservation`, `CountClaimObservation`, `ReductionRecord`, `ObligationClassResult`, `RelationClassResult`, `CoverageRecord`, `RiskRecord`, `ActionRecord`, `RestoredSpan`, `ComponentVersions`, `CertificateTimestamps`, `PreservationCertificate`.
- Fields and enums exactly reflect `certificate-schema.md`.
- Cross-field validators implement schema-local constraints (required restoration list/action relationship, completeness/discovery compatibility, nullable risk fields) but do not claim independent verification.
- `PreservationCertificate` acceptance by Pydantic means “schema valid,” not “preservation verified.”

### API schemas

```python
class CompressionRequest(BaseModel):
    sources: list[SourceInput]
    query: str | None
    target_reduction: Decimal | None
    target_token_budget: int | None
    mode: Literal["safe", "balanced", "aggressive"]
    content_type: str | None
    target_tokenizer: TokenizerIdentity
    return_provenance: bool = True
    return_certificate: bool = True
```

Exactly one of `target_reduction` and `target_token_budget` is required. `target_reduction` is in `[0, 1)`. Sources are non-empty. Phase 1 validates only; it does not process them.

Error response:

```python
class ErrorResponse(BaseModel):
    code: str
    message: str
    run_id: str | None
```

Messages are stable/redacted and contain no request payload.

## Deterministic fixtures

Fixtures are synthetic schema/serialization inputs, not benchmark cases and not evidence of performance.

- `query-null.json`: exact `{ "query": null }` envelope.
- `query-text.json`: one Unicode query covering stable UTF-8 serialization.
- `source-manifest.json`: two ordered synthetic sources proving boundaries/order affect the hash.
- `certificate-synthetic.json`: schema-complete certificate copied from/adapted to the Phase 0 example and labeled synthetic.
- `source-map-synthetic.json`: small original/normalized/compressed map with CRLF and multibyte Unicode coordinates.

Fixtures contain no credentials, private data, model outputs, benchmark scores, or generated benchmark results.

## Acceptance tests

### Packaging and imports

- Editable install succeeds on Python 3.11+.
- `import tracefold` has no network, logging, file-write, model-load, or environment-read side effects.
- All public modules import in a clean process.

### Canonical serialization

- Object key order does not change canonical bytes.
- Array order does change canonical bytes.
- UTF-8 output is stable and has no BOM/trailing newline.
- Duplicate JSON keys, NaN/infinity, invalid Unicode, and unsupported objects are rejected.
- Canonicalizing each fixture twice is byte-identical.

### Hashing

- Hash outputs match committed golden values for canonical fixtures.
- Domain changes alter hashes for identical payloads.
- Null query and empty-string query hashes differ.
- Source manifest reorder/boundary/role change alters aggregate hash.
- Raw bytes are hashed without normalization.

### Schemas

- Every synthetic fixture validates with `extra="forbid"`.
- Unknown/missing required fields and invalid enum/action values fail.
- All four and only the four final actions validate.
- `complete` with `unknown` discovery fails.
- `restore_spans` with an empty restoration list fails.
- `emit` with different raw/final hashes fails schema-local validation.
- Schema validation alone never changes `verification_status` to `passed`.

### Source maps

- Half-open byte/character/line/column ranges validate.
- Negative/reversed/out-of-shape ranges fail.
- Forward and reverse indexes are exact inverses of mapping endpoints.
- Deleted spans permit empty outputs only with `none_deleted`.
- Synthesized summaries cannot declare `byte_exact`.
- Restored mappings require `byte_exact` and non-empty source/output endpoints.
- File paths reject absolute paths and `..`; JSON pointers enforce RFC 6901 escaping.

### Tokenizers

- Fixture tokenizer count equals encoded length.
- Registry resolves exact identity and rejects unknown/duplicate identities.
- Configuration/revision changes produce a different identity.
- There is no implicit default tokenizer.

### Run IDs and logging

- Generated IDs validate as lowercase UUIDv4.
- Fixed test IDs produce deterministic logs.
- Run/attempt IDs appear when bound and disappear after context exit.
- Source/query/context payload strings are absent from log capture.

### CLI and API shells

- Help and version commands exit `0`.
- Schema checks exit `0` for committed fixtures and nonzero for tampered fixtures.
- Compression CLI invocation exits `3` with `PHASE_1_NOT_IMPLEMENTED` and no certificate.
- Health/version routes return exact schema-valid responses.
- Valid compression requests return `501` with the stable error.
- Invalid compression requests return `422` without echoing source payloads.
- No route performs compression, model calls, or verification.

## Non-goals

Phase 1 MUST NOT include:

- real compression or budget selection;
- semantic/protected-obligation extraction;
- document, dialogue, JSON, log, or Python parsing for compression;
- semantic IR, ledger, graph, CPRGC, or content compilers;
- certificate generation from real input;
- independent preservation verification;
- source-map generation from real transformations;
- model calls, embeddings, NLI, target adapters, or hosted APIs;
- risk scoring or calibration;
- restoration, source store, budget expansion, or fallback execution;
- benchmark datasets, adapters, integrations, runs, scores, or reports;
- frontend/demo implementation;
- production deployment or persistence;
- unsupported performance numbers or claims.

## Exact exit commands

Run from the repository root in a clean Python 3.11+ environment:

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
python -m compileall -q src tests
python -m tracefold --help
python -m tracefold version
python -m tracefold schema certificate --check
python -m tracefold schema source-map --check
python -c "from tracefold.api import app; assert app.title == 'TraceFold'"
git diff --check
git status --short
```

Expected results:

- Every command exits `0`.
- `pytest` reports no skips for Phase 1 acceptance tests.
- `git status --short` contains only the intended staged/unstaged Phase 1 allowlist before commit and is clean after the Phase 1 commit.

## Exit gate

Phase 1 exits only when:

1. Every created file is in the allowlist.
2. All public interfaces and schemas above exist and no prohibited package/dependency appears.
3. All exact exit commands pass from a clean environment.
4. Synthetic fixtures are clearly labeled and contain no benchmark result.
5. API/CLI compression paths fail explicitly without fabricating output.
6. `productSpec.md`, `buildPlan.md`, and Phase 0 contracts remain unchanged.
7. Review confirms that schema validity is never presented as independent preservation verification.

The recommended next action after Phase 1 is a separately reviewed contract for deterministic source normalization and source-map generation. It is not authorized by Phase 1 completion alone.
