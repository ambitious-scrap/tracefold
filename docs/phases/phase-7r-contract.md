# Phase 7R Contract: Integrity Remediation and Runnable Public Surface

## Status and authority

Phase 7R is a blocking remediation phase between Phases 7 and 8. It exists because an
external source review found material assurance and usability defects. That review was
not an approval. Phase 0 authority, published schemas, invariants, architecture, and
Phase 1 through Phase 7 contracts retain their existing authority order.

## Objectives and permitted work

Phase 7R repairs tokenizer selection and accounting, compact-verifier independence,
recovery integration, coverage and budget semantics, duplicate/JSON/Python correctness,
diagnostic statuses, package installation, and runnable CLI/API surfaces. Permitted files
are this contract, implementation and schemas needed for those repairs, tests, CI,
optional tokenizer dependency configuration, and regenerated deterministic reports.
Protected product, architecture, invariant, schema, and Phase 0 through Phase 7 contract
documents remain unchanged.

## Production-tokenizer protocol

A tokenizer exposes immutable identity and deterministic `encode`/`count` operations.
Identity contains implementation, identifier, revision, and configuration hash. CPRGC
accepts either an explicit identity resolved through the public registry or a resolved
tokenizer instance. Registration order has no effect. Unknown identities fail before
compression.

`fixture-byte` is fixture-only, is not an LLM tokenizer, and is never labelled provider
token accounting. Optional production tokenization uses `tiktoken` with an explicit
encoding; unknown model-to-encoding inference is forbidden. Configuration uses
`TRACEFOLD_TOKENIZER_BACKEND` and `TRACEFOLD_TOKENIZER_ENCODING`. Provider-reported usage
remains authoritative for live accounting. Requests, CPRGC results, certificates,
reports, and benchmark manifests carry exact tokenizer identity. Fixture-byte and
configured-tokenizer reductions use distinct labels.

## Tokenizer selection

The registry exposes public exact-identity lookup. CPRGC never selects the first
registered item and never accesses private registry state. CLI/API callers resolve an
explicit backend and encoding. A tokenizer instance may be injected only through the
documented library parameter.

## Compact-verifier trust boundary

The compact verifier does not import compressor rendering, graph construction, coverage,
mandatory classification, or ownership assembly. Shared code is limited to immutable
schemas, canonical JSON, domain-separated hashes, tokenizers, coordinate conversion,
low-level parsers, and source-map validation.

Facts are reconstructed from original/normalized source bytes, Phase 2 obligations,
source maps, and compact output. Reconstruction checks obligation class, exact value,
owner/subject, unit, scope, polarity, temporal qualifier, source identity, and evidence
spans. Ambiguous ownership or scope is unverifiable.

Relations are reconstructed from Phase 2 relation records and primary evidence. Checks
cover relation ID/type, exact or inferred class, source identity, evidence spans,
endpoint identities, endpoint direction, and rendering semantics for all 11 frozen
classes: value-unit-owner, rule-exception, condition-consequence,
statement-correction, instruction-scope, definition-use, caller-callee, import-symbol,
event-timestamp, event-trace, and error-causal-predecessor. Metadata agreement alone
cannot establish a relation; fabricated or reversed relations fail.

## Combined verification and recovery

Ordinary certificate and compact-semantic reports are separate evidence. Compact failures
are deterministically converted to canonical `FailedInvariant` records containing stable
ID, class, severity, code, source, obligation/relation IDs, evidence and compressed spans,
expected and observed conditions, recovery hint, and verifier version. They are merged
before Phase 5 risk assessment/action selection. Valid ordinary verification plus invalid
compact verification can never emit. Recovery restores exact evidence, expands budget,
or falls back, then both verifier domains independently re-run.

## Mandatory-obligation policy

Compressor and verifier independently implement the same frozen policy. Mandatory items
include hard obligations, dialogue commitments, anomalous structured rows, code
definitions and guards, exception paths, meaningful severity changes, error/trace/request
identifiers, role boundaries, system/developer instructions, relation endpoints, and
relation evidence. Structurally compressible obligations remain mandatory in semantics,
not necessarily as source copies. Soft observations remain optional. No implementation
function is shared across the trust boundary.

## Coverage denominator

Coverage records include discovered and verified counts, relation-class diversity, exact
count, inferred count, nullable ratio, and status. Zero discovered relations yields
`ratio=null` and `status=not_applicable`; it cannot satisfy a relation-preservation gate.
The Phase 6 structural gate requires non-zero relation instances and multiple classes.

## Budget semantics

Budgets use integer basis points or exact decimal/fraction arithmetic. The token budget is
`floor(original_tokens * remaining_basis_points / 10000)` with exact integer math; 1,000
tokens at 80% reduction yields 200. Explicit token budgets take precedence. Reductions
outside `[0, 1)` and non-positive explicit budgets fail.

After final omission ledger/footer construction CPRGC counts the entire rendered artifact
with the selected tokenizer. If over budget it deterministically removes the lowest
utility safe optional candidate, rebuilds markers, and repeats within a bounded loop.
Mandatory artifacts that cannot fit return `incompressible`; no compliant status may
exceed its final budget.

## Duplicate grouping

`repeated_exact` requires exact source equality after newline normalization only.
Case-folded or whitespace-collapsed groups are labelled `repeated_normalized` or
`normalized_boilerplate`. Normalized grouping is forbidden where differences affect
identifiers, case-sensitive symbols, enum/value/unit/polarity, instructions, code, or JSON
strings.

## JSON paths and indexes

JSON handling supports top-level arrays and arrays beneath arbitrary nested keys. Paths
use RFC 6901 escaping (`~` as `~0`, `/` as `~1`). Grouped rows carry exact indexes or exact
disjoint ranges; non-contiguous indexes are never rendered as one range. Null and missing
remain distinct. Source-map cells retain exact row/path ownership across schema changes.

## Python slicing

Python slicing uses AST boundaries including decorators and supports multiline and async
definitions, classes/methods/nested functions, annotations, `match` guards, multiple
handlers, `finally`, multiline conditions, and non-ASCII source. Synthesized comments or
ellipses are marked synthesized and are never exact source spans. A representation that
promises parseability must pass `ast.parse`; required branches and exception paths are
independently verified.

## Diagnostic statuses

Certificate generation status is one of `unavailable`, `generated_unverified`,
`verified_valid`, `verified_invalid`, or `unverifiable`. Verification status remains a
separate field. Schemas reject contradictory combinations; candidate existence alone
never means valid.

## Public CLI and API

`tracefold tokenizer` prints resolved tokenizer identity without secrets.
`tracefold compress INPUT --kind KIND --mode MODE --tokenizer-backend BACKEND
--tokenizer-encoding ENCODING [--query QUERY]` runs CPRGC; `-` reads stdin. JSON is the
default and includes identity, counts/reductions, compressed context, status/action,
certificate/report, failed invariants, recovery, source-map summary, and warnings.
Expected client errors are concise and omit tracebacks. Benchmark commands remain usable.

`POST /v1/compress` accepts source text/kind/media type/path, mode, optional budget/query,
explicit tokenizer configuration, recovery-attempt cap, and maximum final budget. It
returns the same diagnostic surface. It has no persistence or source-body logging,
sanitizes errors, reports incompressibility explicitly, and rejects unknown tokenizers or
invalid budgets as client errors. Health/version endpoints remain available.

## Package and CI

Built wheels contain package schemas, adapters, CLI/benchmark/report modules, and use
packaged resources rather than repository-relative paths. Public CI on push and pull
request uses CPython 3.11 and runs tests, Ruff check/format, strict mypy, compileall,
package build, wheel-install smoke, CLI/API/schema smoke, deterministic Phase 6 and Phase 7
comparisons, and compression API smoke. CI never performs live inference or requires keys.

## Acceptance tests

Acceptance includes multiple-registration tokenizer-order tests; production tokenizer
resolution; all-field fact tampering; all 11 relation classes and direction attacks;
internally consistent fabricated relation rejection; compact-failure conversion and
end-to-end recovery; mandatory-policy differential tests; zero-relation not-applicable;
integer and footer-growth budget boundaries; exact/normalized duplicate counterexamples;
generic RFC 6901 arrays and disjoint indexes; hardened parseable Python slices; diagnostic
status validation; CLI/API success, incompressible, and client-error cases; replay
tokenizer mismatch; wheel installation; deterministic report and prepared-artifact
comparison; and protected/local-only file checks.

## Explicit non-goals

No UI, deployment, live benchmark, target-model call, model training, neural compressor,
new benchmark question/answer, 95% retention claim, broad refactor, Phase 8 work, merge,
or pull request is permitted.

## Exit commands

```text
python3.11 -m venv .venv-review
.venv-review/bin/python -m pip install --upgrade pip
.venv-review/bin/python -m pip install -e ".[dev]"
.venv-review/bin/pytest -q
.venv-review/bin/ruff check src tests
.venv-review/bin/ruff format --check src tests
.venv-review/bin/mypy src tests
.venv-review/bin/python -m compileall -q src
.venv-review/bin/python -m build
.venv-review/bin/python -m tracefold --help
.venv-review/bin/python -m tracefold tokenizer --help
.venv-review/bin/python -m tracefold compress --help
.venv-review/bin/python -m tracefold benchmark --help
.venv-review/bin/python -c "from tracefold.api import app; print(app.title)"
.venv-review/bin/python -m tracefold.phase6_report
.venv-review/bin/python -m tracefold.phase7_report
git diff --check
```

Then install the built wheel in a second clean environment and run CLI help, API import,
one compression fixture, and schema checks. Run deterministic Phase 6 reports and Phase 7
prepare twice and compare canonical outputs. Verify protected-file diff is empty.
