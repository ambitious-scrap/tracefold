# TraceFold Phase 0 Approval Record

Status: **APPROVED**

Approval basis: independent adversarial architecture review of Phase 0 commit `6c60c366a5ae7cbfe8c9dfc89eb269dbd10e3569`, followed by the documentation-only corrections recorded here.

Normative inputs: `productSpec.md`, `buildPlan.md`, the six Phase 0 contract documents, and the Phase 0 approval-gate instructions.

This approval does not authorize product implementation. It authorizes merging the approved documentation and creating an empty `phase/1-scaffolding` branch.

## Gate result

- Phase 0 result: **APPROVED**.
- `PROJECT_BLOCKER`: none.
- `PHASE_1_BLOCKER`: none after the `RESOLVED_NOW` corrections below.
- Remaining open items: `DEFERRED_WITH_OWNER` only.
- Application code added during Phase 0 or approval: none.
- Benchmark/performance results added: none.
- Source specifications modified: none.

## Synchronization and source-integrity evidence

At approval review start:

- branch: `phase/0-proof-contract`;
- HEAD: `6c60c366a5ae7cbfe8c9dfc89eb269dbd10e3569`, exactly the expected Phase 0 commit;
- remote: `https://github.com/ambitious-scrap/tracefold.git`;
- tracked branch state: synchronized with `origin/phase/0-proof-contract` and clean;
- `productSpec.md` SHA-256: `c853a055b7072a39c56be9d95e2e93e2ad90ad179146707641ceac5ce3420539`;
- `buildPlan.md` SHA-256: `d88b639d4618981075cd9e57e3a4f98675426a42e20f30cc58ca943038487f28`;
- both specification files are byte-identical to initial commit `2fbf07143e4d2ce5c9fafd250e5e6fa2b79c5cab`;
- all six required Phase 0 documents existed;
- the tracked tree contained only `.gitignore`, the two specifications, and the six Phase 0 documents—no application code.

Workspace warning: untracked `AGENTS.md` and `.serena/` files were present. They are local instruction/runtime artifacts, are not part of the branch, and are excluded from every stage and commit. Their presence means an unqualified `git status` is not literally empty even though the tracked branch state is clean.

## Adversarial review findings

| Review target | Result |
|---|---|
| Compressor/verifier trusted-state separation | Pass. The verifier may share immutable schemas, hash/tokenizer interfaces, and independently invoked parser adapters, but cannot import compressor decisions, scores, selectors, or pass flags. |
| Independent recomputability | Pass after A-01 through A-03. Proof-bearing claims have verifier observations or deterministic replay; timestamps and other non-recomputable metadata are explicitly informational. |
| Normalization-safe coordinates | Pass. Original, normalized, and output coordinates are artifact-specific, UTF-8 byte ranges are authoritative, and stale maps block certification. |
| Raw versus repaired artifacts | Pass after A-01 and A-03. Shared-domain content hashes permit identity checks; distinct fields, attempt IDs, and immutable recovery records preserve lifecycle identity. |
| Query binding | Pass. Every run hashes an exact query envelope, including `{"query": null}`. |
| Fallback transparency | Pass. Raw failures survive in history and raw/certified/end-to-end reporting remains separate. |
| Unknown discovery coverage | Pass. Unknown or partial discovery cannot produce a complete-preservation claim. Full fallback may prove byte identity without relabeling discovery as complete. |
| Synthesized summaries | Pass. They require source contributors, carry semantic-lineage-only mappings, and cannot satisfy byte-exact obligations by paraphrase. |
| Canonical actions | Pass after A-03. The only final actions are `emit`, `restore_spans`, `expand_budget`, and `full_fallback`. |
| Module dependency cycles | Pass. The recovery loop is an orchestration cycle over immutable artifacts, not a forbidden import cycle; verifier dependencies remain one-way. |
| Phase 1 algorithm leakage | Pass. Phase 1 reserves schemas and shells but contains no extraction, compilation, verification, model, calibration, recovery, benchmark, or frontend behavior. |
| Pydantic and JSON Schema representability | Pass after A-05 through A-08. Models use explicit discriminators/enums, cross-field validators, canonical exports, and no unsupported JSON values. |
| Security-critical labeling | Pass. Security-relevant identities, evidence, action, policy, history, and component/config bindings are critical; timestamps remain informational. |
| Stale certificate/source detection | Pass. Source, query, request, context, and map hashes are independently rebound; map mutations force stale/failure. |
| Append-only recovery | Pass after A-02. Sequence, event links, event hashes, history head/count, compare-and-append behavior, and verifier-recomputed history hash are frozen. |

## Approval correction decision records

Each correction is documentation-only and is a `RESOLVED_NOW` project decision.

### A-01 — One content hash domain for raw, restored, and final contexts

- **Classification:** `RESOLVED_NOW`.
- **Defect:** `certificate-schema.md` assigned different hash domains to raw and final contexts while also requiring their hashes to be equal for `emit`. Domain separation made equality impossible even for identical bytes.
- **Decision:** All context lifecycle artifacts use `tracefold:context-artifact:1`; lifecycle role remains in field/stage identity and recovery history.
- **Reason:** Content identity and lifecycle identity are different concepts.
- **Impact if wrong:** Every valid raw `emit` would fail, or implementations would bypass the documented hash contract.
- **Files corrected:** `architecture.md`, `certificate-schema.md`, `source-map-schema.md`, and `phases/phase-1-contract.md`.

### A-02 — Recovery history integrity and append semantics

- **Classification:** `RESOLVED_NOW`.
- **Defect:** The history was called append-only but only contained mutable array entries and references.
- **Decision:** Freeze zero-based sequences, prior-event hashes, per-event hashes, a claimed/verified ordered-history hash, record count, head hash, and compare-and-append runtime behavior.
- **Reason:** Resolved raw failures must remain detectable and cannot be rewritten as successful attempts.
- **Impact if wrong:** Recovery could erase evidence and fallback could camouflage raw failures.
- **Files corrected:** `architecture.md`, `certificate-schema.md`, and `phases/phase-1-contract.md`.

### A-03 — Verifiable `expand_budget` evidence

- **Classification:** `RESOLVED_NOW`.
- **Defect:** The certificate required old/new budgets but recovery records did not carry them, and validation ambiguously required a larger output token count.
- **Decision:** Every attempt records `effective_token_budget`; `expand_budget` requires a strictly larger next-attempt budget, not a larger emitted artifact.
- **Reason:** An enlarged budget is a controller input; output size may remain lower after recompilation.
- **Impact if wrong:** A valid expansion could fail, or an unproven expansion could pass.
- **Files corrected:** `certificate-schema.md` and `phases/phase-1-contract.md`.

### A-04 — Complete source-map artifact hash domains

- **Classification:** `RESOLVED_NOW`.
- **Defect:** Source-map artifacts required per-stage hashes, but original and normalized artifact domains were not defined.
- **Decision:** Freeze source-artifact, normalized-artifact, and shared context-artifact domains with exact byte inputs.
- **Reason:** Stale-map verification cannot be interoperable without exact hash domains.
- **Impact if wrong:** Compressor and verifier could disagree about unchanged artifacts or miss normalization drift.
- **Files corrected:** `source-map-schema.md` and `phases/phase-1-contract.md`.

### A-05 — Exact Phase 1 Python runtime and command

- **Classification:** `RESOLVED_NOW`.
- **Defect:** The contract said Python `3.11+` and used `python`, but the approval workspace has no `python` executable and an unbounded runtime was not an exact support statement.
- **Decision:** Phase 1 supports CPython `3.11.x`, declares `>=3.11,<3.12`, and uses `python3.11` in every exact command.
- **Reason:** The scaffold gate must run identically in the declared environment.
- **Impact if wrong:** Luna could produce a scaffold whose documented exit gate cannot execute.
- **File corrected:** `phases/phase-1-contract.md`.

### A-06 — Dependency-management and canonicalizer implementation

- **Classification:** `RESOLVED_NOW`.
- **Defect:** `pyproject.toml` and pip were implied, but the build backend, dev-extra layout, and RFC 8785 implementation were unspecified.
- **Decision:** Use PEP 621, Hatchling, pip, a `dev` optional extra, major-bounded dependencies, and the `rfc8785` package rather than a hand-rolled canonicalizer.
- **Reason:** Packaging and canonical bytes are compatibility boundaries, not implementation trivia.
- **Impact if wrong:** Installs or hashes could differ between implementations.
- **File corrected:** `phases/phase-1-contract.md`.

### A-07 — Closed Phase 1 hash-domain registry

- **Classification:** `RESOLVED_NOW`.
- **Defect:** Hash functions accepted arbitrary strings even though domain spelling is security-critical.
- **Decision:** Public hashing functions take a closed `HashDomain` enum covering all Phase 0 domains and add exactly one NUL separator.
- **Reason:** Typos or ad hoc domains must fail before producing incompatible hashes.
- **Impact if wrong:** Independently implemented components could hash identical artifacts incompatibly.
- **File corrected:** `phases/phase-1-contract.md`.

### A-08 — Public JSON Schema publication location

- **Classification:** `RESOLVED_NOW`.
- **Defect:** External schema publication was left unresolved even though Phase 1 must expose clean JSON Schema artifacts.
- **Decision:** Commit canonical exports at `schemas/v1/preservation-certificate.schema.json` and `schemas/v1/source-map.schema.json` with immutable URN IDs; compare regenerated schemas byte-for-byte in `--check` commands.
- **Reason:** Repository paths and IDs can be stable before an external domain exists.
- **Impact if wrong:** External consumers and Pydantic implementations could drift before the first release.
- **File corrected:** `phases/phase-1-contract.md`.

### A-09 — Canonical invariant IDs in source-map examples

- **Classification:** `RESOLVED_NOW`.
- **Defect:** Several example IDs used hyphens, a `relation:` prefix, or class names absent from the invariant registry.
- **Decision:** Use the exact canonical class names and `obl:`/`rel:` ID prefixes from `invariants.md`.
- **Reason:** Examples are contract fixtures for implementers and must not teach incompatible identifiers.
- **Impact if wrong:** Schema fixtures and verifier lookups could disagree despite valid JSON.
- **File corrected:** `source-map-schema.md`.

### A-10 — Run-ID version consistency

- **Classification:** `RESOLVED_NOW`.
- **Defect:** The certificate allowed any RFC 4122 UUID while the Phase 1 public interface required UUIDv4.
- **Decision:** Run IDs are lowercase RFC 4122 UUIDv4 throughout.
- **Reason:** One public format must be authoritative.
- **Impact if wrong:** A certificate could pass one schema and fail another.
- **File corrected:** `certificate-schema.md`.

### A-11 — Full-fallback verification meaning

- **Classification:** `RESOLVED_NOW`.
- **Defect:** `passed` generally depended on discovery completeness, while full fallback is correct by bound byte/role identity even when discovery is unknown.
- **Decision:** Full fallback may pass exact artifact/framing verification while retaining `partial` or `unknown` semantic completeness; it never becomes a raw certified compression success.
- **Reason:** Correctness fallback should not fabricate analyzer completeness.
- **Impact if wrong:** Dense/unsupported inputs would either be mislabeled complete or could never produce a valid fallback record.
- **File corrected:** `certificate-schema.md`.

## Classification of the Phase 0 contradiction register

Each contradiction from `PHASE_0_CONTRACT.md` has exactly one classification.

| ID | Classification | Approval disposition |
|---|---|---|
| C-01 | `APPROVED_DECISION` | Keep `priority:P0` distinct from delivery `phase:0`; Phase 0 is documentation-only. |
| C-02 | `APPROVED_DECISION` | The scaffolding-only Phase 1 contract supersedes the legacy feature-phase label for the next implementation branch. |
| C-03 | `APPROVED_DECISION` | Phase 0 freezes fixture/verification shapes in prose; executable fixtures begin in Phase 1. |
| C-04 | `APPROVED_DECISION` | Canonical certificate names and nesting are authoritative; external adapters may use unsigned compatibility aliases. |
| C-05 | `APPROVED_DECISION` | The four canonical final actions include `restore_spans`. |
| C-06 | `APPROVED_DECISION` | Claim generation and independent verification remain separate packages and trust domains. |
| C-07 | `APPROVED_DECISION` | Only preservation claims require recomputation; informational metadata cannot create a pass. |
| C-08 | `APPROVED_DECISION` | Every run hashes an explicit query envelope, including null query. |
| C-09 | `APPROVED_DECISION` | Coverage and discovery status remain separate; unknown discovery prohibits completeness. |
| C-10 | `APPROVED_DECISION` | Artifact-specific, half-open coordinate semantics are authoritative. |
| C-11 | `APPROVED_DECISION` | Exact-copy, lineage, and protected-item map coverage remain separate. |
| C-12 | `APPROVED_DECISION` | Freeze the tokenizer interface/identity tuple per run, not one global tokenizer. |
| C-13 | `APPROVED_DECISION` | Draft, independent observation, risk/action, recovery, reverification, and final sealing form the certificate lifecycle. |
| C-14 | `APPROVED_DECISION` | Raw and final context identities remain distinct; A-01 makes byte equality computable. |
| C-15 | `APPROVED_DECISION` | Risk always carries calibration status; only calibrated values are probabilities. |
| C-16 | `APPROVED_DECISION` | Source-store interface is required; run-scoped memory is default and durable storage is opt-in. |
| C-17 | `APPROVED_DECISION` | JSON and log plugins remain distinct under shared structured utilities. |
| C-18 | `APPROVED_DECISION` | SIR is internal and exposed only through authorized explain/report boundaries. |
| C-19 | `APPROVED_DECISION` | Correctness-open means exact larger/full context or explicit error, never authorization bypass. |
| C-20 | `APPROVED_DECISION` | Per-source hashes plus an ordered canonical manifest define multi-source identity. |
| C-21 | `APPROVED_DECISION` | Verification status, selected action, and benchmark acceptance remain distinct. |
| C-22 | `APPROVED_DECISION` | Structured counts are compressor claims; the verifier reparses and records independent counts. |

## Classification of unresolved questions

Each unresolved question from `PHASE_0_CONTRACT.md` has exactly one classification. Deferred items name an owner phase, why deferral is safe, the latest decision point, and the interface that must remain stable.

### Q-01 — Final tokenizer identities and revisions

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** target-model adapter phase (legacy build-plan Phase 5).
- **Safe to defer because:** Phase 1 implements identity and registry contracts only and has no production tokenizer.
- **Latest resolution point:** before the first paired target-model or benchmark run is frozen.
- **Stable interface:** `TokenizerIdentity` and exact registry lookup; no implicit default.

### Q-02 — Safe/balanced/aggressive risk thresholds

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** risk calibration and recovery phase (legacy build-plan Phase 4).
- **Safe to defer because:** Phase 1 represents nullable thresholds and calibration status but makes no acceptance decision.
- **Latest resolution point:** before any certified operating point or automated `emit` policy is enabled.
- **Stable interface:** `RiskRecord`, `ActionRecord`, calibration-status enum, and versioned policy ID.

### Q-03 — Logistic versus isotonic calibrator

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** risk calibration and recovery phase.
- **Safe to defer because:** Selection requires validation data and does not affect Phase 1 serialization.
- **Latest resolution point:** before the first calibrator artifact is frozen.
- **Stable interface:** calibrator ID/version, feature-manifest hash, score/recomputed score, and calibration status.

### Q-04 — HELMET, LongBench v2, and RULER slices

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** benchmark harness/configuration phase (legacy build-plan Phase 6).
- **Safe to defer because:** Phase 1 contains no benchmark package or result schema implementation.
- **Latest resolution point:** before dataset configs/splits are frozen for benchmark runs.
- **Stable interface:** immutable dataset/config/split identities and separate raw/certified/end-to-end records.

### Q-05 — Headroom reproducibility

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** competitor-integration portion of the benchmark phase.
- **Safe to defer because:** No competitor integration is permitted in Phase 1.
- **Latest resolution point:** before the matched-budget comparison table is frozen.
- **Stable interface:** explicit unavailable/error rows; no fabricated or substituted results.

### Q-06 — DAC benchmark budget

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** post-core benchmark expansion phase.
- **Safe to defer because:** DAC is a priority-P1 product goal, not scaffolding and not a release-critical interface.
- **Latest resolution point:** before final benchmark scope freeze.
- **Stable interface:** method adapter identity, matched token budget, and explicit unavailable status.

### Q-07 — Final ContextProofBench size and release scope

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** corruption-fixture/benchmark phase.
- **Safe to defer because:** Phase 1 fixtures are synthetic schema fixtures and cannot be presented as benchmark data.
- **Latest resolution point:** before validation/test splits and public-release claims are frozen.
- **Stable interface:** deterministic fixture IDs, gold-obligation schema, split hash, and no benchmark-result claims in Phase 1.

### Q-08 — Target-model families and hosted provider

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** target-model adapter phase.
- **Safe to defer because:** No model calls or adapters are permitted in Phase 1.
- **Latest resolution point:** before paired full/compressed inference begins.
- **Stable interface:** target model/tokenizer/config identities and identical-settings comparison contract.

### Q-09 — Durable source-storage policy

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** source-store and recovery implementation phase.
- **Safe to defer because:** The approved default remains run-scoped memory with no persistence; Phase 1 implements no store.
- **Latest resolution point:** before any durable backend or retrieval endpoint is enabled.
- **Stable interface:** content-addressed source reference, explicit opt-in, authorization context, retention policy, and exact-byte retrieval.

### Q-10 — Evidence sufficient for `discovery_status: known`

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** typed-analyzer/invariant-detector phase.
- **Safe to defer because:** Phase 1 can represent the enum but cannot emit discovery evidence from real content.
- **Latest resolution point:** before any analyzer is permitted to output `known` or any certificate claims `complete`.
- **Stable interface:** per-analyzer applicability, support-envelope version, detector completion, parser warnings, and registry version.

### Q-11 — Dynamic Python fallback boundaries

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** Python analyzer/compiler phase.
- **Safe to defer because:** Phase 1 includes no Python parsing or compression.
- **Latest resolution point:** before dynamic/reflection-heavy Python can be certified or compressed.
- **Stable interface:** unresolved-symbol/path observations yield `indeterminate` and broader restoration/fallback.

### Q-12 — TypeScript support

- **Classification:** `RESOLVED_NOW`.
- **Decision:** TypeScript, JavaScript, Node.js, frontend tooling, and TypeScript schemas are outside Phase 1. Version 1 code-content contracts remain Python-specific. Any later TypeScript support requires a separately approved phase contract.
- **Reason:** Nothing in the Phase 1 scaffold requires TypeScript, and the build plan labels it stretch scope.

### Q-13 — NLI and differential-probe requirements

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** independent-verifier/benchmark policy phase.
- **Safe to defer because:** Phase 1 does not verify real content; probabilistic probes cannot replace frozen structural checks.
- **Latest resolution point:** before declaring a certified operating point for a content/task class whose hard checks are not structurally decidable.
- **Stable interface:** probe results remain labeled auxiliary observations with component/version/config identity and cannot self-certify.

### Q-14 — Public JSON Schema publication location

- **Classification:** `RESOLVED_NOW`.
- **Decision:** Version `1.0.0` certificate and source-map schemas publish at the two `schemas/v1/` repository paths and immutable URN IDs defined by A-08. External HTTPS hosting is a byte-identical mirror, not the authoritative identity.
- **Reason:** Phase 1 needs a stable public interoperability artifact but no public domain is established.

### Q-15 — Final product name and category wording

- **Classification:** `DEFERRED_WITH_OWNER`.
- **Owning future phase:** demo/pitch/submission phase (legacy build-plan Phases 9–10).
- **Safe to defer because:** The package/repository identifier `tracefold` is frozen independently of public marketing copy.
- **Latest resolution point:** before README, slide, deployed UI, and submission copy freeze.
- **Stable interface:** Python package, CLI command, schema IDs, repository name, and API service title remain `tracefold`/`TraceFold` for version 1.

## Phase 1 readiness decisions

| Required decision | Classification | Frozen result |
|---|---|---|
| Supported Python | `RESOLVED_NOW` | CPython `3.11.x`; `>=3.11,<3.12`; command `python3.11`. |
| Package/module name | `APPROVED_DECISION` | Distribution/import/CLI root `tracefold`. |
| Dependency management | `RESOLVED_NOW` | PEP 621 + Hatchling + pip + `.[dev]`; no Phase 1 lockfile. |
| Pydantic major | `APPROVED_DECISION` | Pydantic v2 (`>=2,<3`). |
| Canonical serialization | `RESOLVED_NOW` | RFC 8785 project profile via `rfc8785`; strict parse; UTF-8/no BOM/no trailing newline. |
| Hash algorithm and bytes | `RESOLVED_NOW` | Domain-separated SHA-256 over exact bytes or canonical JSON bytes; one NUL separator; closed domains. |
| Run-ID format | `RESOLVED_NOW` | Lowercase RFC 4122 UUIDv4. |
| Public schema publication | `RESOLVED_NOW` | Two canonical exports under `schemas/v1/` with immutable URN IDs. |
| CLI choice | `APPROVED_DECISION` | Typer shell. |
| FastAPI entry point | `APPROVED_DECISION` | `tracefold.api:app`. |
| Test command | `RESOLVED_NOW` | `python3.11 -m pytest -q`. |
| Lint command | `RESOLVED_NOW` | `python3.11 -m ruff check .`. |
| Type-check command | `RESOLVED_NOW` | `python3.11 -m mypy src tests` in strict mode. |
| TypeScript in Phase 1 | `RESOLVED_NOW` | Explicitly excluded. |

## Residual architecture risks

These risks do not block deterministic scaffolding, but they can invalidate later product claims if their owner phases fail to resolve them:

1. Shared third-party parser defects can correlate compressor and verifier failures even when mutable state and decision logic are independent. Later verifier tests need adversarial parser-differential fixtures.
2. `discovery_status: known` has no content-type evidence profile yet. No later phase may claim completeness before Q-10 is resolved.
3. A hash-bound certificate proves consistency with supplied artifacts and policy; it does not by itself authenticate who produced the artifacts. Any hostile-transport authenticity claim needs a separately reviewed signing/attestation policy.
4. Durable source storage could violate privacy or access boundaries; the in-memory default must remain until Q-09 is resolved.
5. Dynamic Python behavior may defeat static dependency evidence; unresolved dispatch must remain indeterminate and correctness-open.
6. Canonical schema exports can drift from Pydantic models unless Phase 1's byte-for-byte regeneration checks are mandatory.
7. Raw/certified/end-to-end benchmark records can still be misreported by downstream presentation code; reporting/UI must remain read-only consumers of immutable artifacts.

## Approval exit criteria

Phase 0 is approved only with all of these checks passing on the approval commit:

- source specifications retain the hashes recorded above;
- only documentation under `docs/` changed from the frozen Phase 0 commit;
- all JSON examples parse with duplicate-key rejection;
- certificate examples satisfy the documented field/action relationships;
- all source-map example coordinates and invariant identifiers validate;
- the invariant registry contains exactly 29 obligation classes and 11 relation classes;
- every canonical action occurrence uses one of the four frozen names;
- Phase 1 has one authoritative public interface definition and exact build/test/lint/type/schema commands;
- no benchmark result, application code, model integration, or frontend artifact exists;
- `git diff --check` passes.

After these checks, merge with `--no-ff`, push `main`, and create/push `phase/1-scaffolding` without implementing it.
