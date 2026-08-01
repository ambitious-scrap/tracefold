# TraceFold Phase 0 Contract

Status: architecture and proof-contract freeze

Contract version: `phase-0/1.0`

Normative sources: `productSpec.md`, `buildPlan.md`, and the Phase 0 task instructions

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative. A statement marked **[PROPOSED PROJECT DECISION]** is a new engineering decision that is not explicit in the source specifications. It becomes frozen for implementation when this contract is accepted; it does not rewrite either source specification.

## Phase objective

Convert the product vision and deadline-oriented build plan into a testable engineering contract for proof-carrying context compression. Phase 0 freezes boundaries, data contracts, preservation invariants, source mapping, verification trust, recovery actions, and the next phase's scaffolding scope. It produces documentation only.

The phase succeeds when two implementers can independently build compatible Phase 1 scaffolds without guessing field meaning, trust ownership, offset semantics, action semantics, or phase scope.

## Inputs

- `productSpec.md`, read as the product, research, safety, evaluation, and positioning specification.
- `buildPlan.md`, read as the deadline-aware implementation ordering and scope-control plan.
- The Phase 0 task instructions, which narrow this phase to architecture and contracts and define the required Phase 1 scope.
- The clean `main` commit from which `phase/0-proof-contract` was created.

## Outputs

- `docs/PHASE_0_CONTRACT.md`: scope, decisions, contradiction register, acceptance criteria, and exit gate.
- `docs/architecture.md`: module ownership, dataflow, trust boundaries, dependencies, and failure behavior.
- `docs/invariants.md`: protected obligation and relation invariants.
- `docs/certificate-schema.md`: versioned preservation-certificate contract and complete synthetic example.
- `docs/source-map-schema.md`: exact original/normalized/compressed lineage contract and mapping examples.
- `docs/phases/phase-1-contract.md`: scaffolding-only contract for the next phase.

## Decisions being frozen

### Source of truth and precedence

1. The source specifications remain unchanged and retain their evidence labels.
2. Where the source specifications agree, this contract makes the shared requirement normative.
3. Where they conflict or are underspecified, the issue is recorded below. A resolution marked **[PROPOSED PROJECT DECISION]** is the implementation rule for this branch, subject to project-owner approval.
4. The explicit Phase 0 task instructions control the scope of this phase and the explicit Phase 1 task instructions control the scope of Phase 1.

### Proof and trust

1. The compressor and independent verifier are separate logical components with one-way artifact exchange. They MUST NOT share mutable decision state or accept compressor pass/fail flags as evidence.
2. The verifier receives the original artifacts, query envelope, emitted context, source map, certificate claims, and versioned verification policy. It independently parses and recomputes preservation evidence.
3. No LLM may certify its own compression output. Model-generated or probabilistic signals MAY be evidence inputs, but deterministic checks and an independent component make the certificate decision.
4. Every preservation claim MUST be independently recomputable. Non-preservation metadata such as wall-clock timestamps is explicitly informational and MUST NOT be used as proof.
5. Exact protected values MUST NOT be paraphrased. Relations are first-class obligations; retaining isolated tokens is insufficient.
6. A certificate MUST NOT claim complete preservation when obligation discovery coverage is `unknown` or when any required analyzer did not run successfully.

### Artifacts, serialization, and hashes

1. **[PROPOSED PROJECT DECISION]** Contract schemas use semantic version `1.0.0`; incompatible meaning or required-field changes require a major version change.
2. **[PROPOSED PROJECT DECISION]** All contract JSON is UTF-8, uses canonical key ordering and canonical number/string encoding defined in `docs/certificate-schema.md`, and is hashed with SHA-256 using lowercase hexadecimal prefixed by `sha256:`.
3. The source hash covers original bytes, not normalized text. Normalized and emitted artifacts have distinct hashes.
4. Query-dependent runs always carry a query hash. **[PROPOSED PROJECT DECISION]** An absent query is represented by a canonical null query envelope and is hashed; the field is never omitted.
5. **[PROPOSED PROJECT DECISION]** The certificate also binds a canonical compression-request hash so requested reduction/budget, mode, content hint, tokenizer identity, source manifest, and query cannot be changed after verification.
6. Tokenizer identity includes implementation, vocabulary/model identifier, and revision. Token counts without that identity are invalid claims.

### Source mappings

1. Original source bytes are immutable for a run.
2. Mappings form an explicit, bidirectional lineage graph from original to normalized to compressed artifacts.
3. Byte, character, line, and column coordinates have fixed bases and half-open interval semantics defined in `docs/source-map-schema.md`.
4. Deleted and synthesized spans remain represented as lineage records; absence from compressed output MUST NOT erase provenance.
5. Source-map hashes MUST match all mapped artifacts. A mismatch makes the map stale and blocks certification.

### Recovery and reporting

1. The only final actions are `emit`, `restore_spans`, `expand_budget`, and `full_fallback`.
2. Recovery is monotonic toward correctness: restored exact source material is not removed again within the same recovery chain.
3. Parser, verifier, stale-map, unknown-coverage, and dense-input failures expand or fall back; they never silently accept a shorter prompt.
4. Raw, certified, and end-to-end results are separate immutable observations. Recovery MUST NOT rewrite or hide raw compressor failures.
5. The certificate describes the final emitted artifact and links to the raw artifact and recovery events when recovery occurred.

### Phase boundaries

1. Phase 0 creates documentation only.
2. Phase 1 creates project scaffolding, schemas, canonical serialization, hashes, tokenizer abstraction, CLI/API shells, run IDs/logging, fixtures, and a CI-ready test command only.
3. Compression, extraction, model calls, calibration, benchmark integrations, recovery algorithms, and frontend work are outside Phase 1.

## Explicit non-goals

- Implementing CPRGC, a compressor, semantic extraction, or any content compiler.
- Implementing a working compression API, target-model calls, recovery, calibration, or a verifier engine.
- Creating benchmark datasets, running benchmarks, or claiming any measured result.
- Selecting final benchmark datasets, target models, hosted providers, or operating thresholds.
- Building the demo UI, gateway integration, deployment, slides, or submission artifacts.
- Changing `productSpec.md` or `buildPlan.md`.
- Claiming universal losslessness, universal compressibility, or benchmark performance.
- Resolving research questions by assertion.

## Source traceability review

| Contract area | Supporting source requirements | Phase 0 treatment |
|---|---|---|
| Typed pipeline and content routing | `productSpec.md` §§5.4–5.5, 7, 13; `buildPlan.md` §§1, 4, 6 | Module/data boundaries frozen; implementation deferred. |
| Independent verification | `productSpec.md` §§5.8–5.9 and FR-2; `buildPlan.md` §§2.1, 7.1 | Separate trust domain; compressor flags are never evidence. |
| Protected classes and relations | `productSpec.md` §§5.7, 8, 9; `buildPlan.md` §§1, 6.2, 7 | Required registry operationalized in `invariants.md`. |
| Query binding | `productSpec.md` §§5.8, 9.5, 20; `buildPlan.md` §§7.1, 9.1 | Canonical query envelope/hash required, including null query. |
| Source mapping and exact restoration | `productSpec.md` §§5.3, 5.9, 7–9, 19.6, 20; `buildPlan.md` §§2.1, 6.1, 7.3, 9.1 | Coordinate, lineage, stale-map, and restore contracts frozen. |
| Certificate claims and coverage | `productSpec.md` §§5.8, 12, 19.5, 20; `buildPlan.md` §§6.1–6.2, 7.1 | Claim/observation ownership and unknown-discovery limits frozen. |
| Risk and recovery | `productSpec.md` §§5.9, 9.3, 20; `buildPlan.md` §§6.7, 7.3, 14 | Calibration labels and four-action lifecycle frozen; model/threshold unresolved. |
| Raw/certified/end-to-end reporting | `productSpec.md` §§4.1, 18.2, 20; `buildPlan.md` §§1–2, 8.4–8.5 | Artifact identities and append-only recovery history frozen. |
| Tokenization, serialization, and hashes | `productSpec.md` §§5.2, 5.8, 12, 18.3; `buildPlan.md` §§5, 9.1, 10 | Per-run tokenizer identity and proposed canonical/hash profile frozen. |
| Correctness fallback | `productSpec.md` §§5.9, 12, 20; `buildPlan.md` §§2.4, 7.3, 14 | Dense/failure path expands, falls back, or errors; never silently shortens. |
| Phase 1 scaffolding | Current Phase 0 task; prerequisites implied by `buildPlan.md` §§4, 6.1, 9.1, 18 | Exact proposed allowlist/interfaces/tests in `phases/phase-1-contract.md`. |

No architecture claim in the six outputs is presented as measured performance. Details not stated by these source sections are marked **[PROPOSED PROJECT DECISION]** at the applicable document or section scope.

## Contradiction and ambiguity register

No issue in this section is silently resolved. Proposed resolutions are explicit project decisions for review.

### C-01 — “P0” and numbered “Phase 0” describe different scopes

- **Source and section:** `productSpec.md` §4.1 “P0 goals”; `buildPlan.md` §2.1 “P0, must ship”; `buildPlan.md` §5 “Phase 0: Lock the proof contract”; Phase 0 task instructions.
- **Conflicting statements:** Product/build-plan “P0” means the complete must-ship product. Build-plan “Phase 0” also requires schemas, ten adversarial cases, and a verifiable fixture. The current Phase 0 instruction permits contract documentation only.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Reserve `priority:P0` for release priority and `phase:0` for this documentation freeze. No executable fixture or benchmark case is created in this phase.
- **Reason:** Priority and delivery phase are independent dimensions; using one label for both makes gates untestable.
- **Impact if wrong:** Teams may start product implementation early or falsely mark the must-ship product complete after a documentation phase.

### C-02 — Phase 1 scope conflicts with the build-plan schedule

- **Source and section:** `buildPlan.md` §5 “Phase 1: Typed obligations and source map”; Phase 1 task instructions in this phase request.
- **Conflicting statements:** The build plan puts extraction and exact source mapping in Phase 1. The current instruction limits Phase 1 to scaffolding, schemas, serialization, hashes, tokenization, shells, logging, fixtures, and test commands, and explicitly forbids semantic extraction.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** The new `docs/phases/phase-1-contract.md` governs the next implementation phase. The build-plan feature phase is renumbered in execution planning later; `buildPlan.md` remains unchanged.
- **Reason:** The explicit current task is narrower and creates prerequisites for the build-plan work.
- **Impact if wrong:** Phase 1 would smuggle in unreviewed semantics and make schema changes expensive after implementation.

### C-03 — Build-plan Phase 0 requires executable proof artifacts

- **Source and section:** `buildPlan.md` §5 “Phase 0: Lock the proof contract” exit criterion; current Phase 0 prohibition on product code.
- **Conflicting statements:** The build plan exits when a certificate fixture can be independently verified and requests ten adversarial cases; the current task forbids implementation and benchmarks.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Phase 0 freezes fixture shapes and acceptance tests in prose. Executable fixtures begin in Phase 1; executable independent verification occurs only in a later verifier phase.
- **Reason:** A real verification exit requires code, while this phase is contract-only.
- **Impact if wrong:** The phase either violates scope or claims executable assurance that does not exist.

### C-04 — Certificate field names and nesting disagree

- **Source and section:** `productSpec.md` §5.8 certificate example; `productSpec.md` §11 FR-1 response; `buildPlan.md` §6.1 core schemas.
- **Conflicting statements:** Examples alternate among `certificate_version`/`version`, `compressed_hash`/`compressed_context` concepts, `target_tokenizer`/`tokenizer`, `tokens_before`/`original_tokens`, `tokens_after`/`compressed_tokens`, nested `risk`/`predicted_answer_change`, and `decision`/`status`.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Adopt the canonical names and claim/observation separation in `docs/certificate-schema.md`; adapters may expose compatibility aliases only outside the signed/canonical object.
- **Reason:** Hashing, schema validation, and independent recomputation require one representation.
- **Impact if wrong:** Compressor and verifier could hash or interpret different payloads and produce false mismatches or false passes.

### C-05 — The recovery action set is internally inconsistent

- **Source and section:** `productSpec.md` §5.3 and §11.8; `buildPlan.md` §5 Phase 0; `buildPlan.md` §7.3 recovery policy.
- **Conflicting statements:** Most sections define four actions, including `restore_spans`; build-plan §7.3 says “Stop at `emit`, `expand_budget`, `full_fallback`,” omitting `restore_spans` even though the same section describes restoration.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Freeze all four allowed final actions. `restore_spans` is a first-class terminal action for a repaired emitted artifact, not merely an internal event.
- **Reason:** Restoration is central to the product claim and must be observable.
- **Impact if wrong:** Restored outputs could be mislabeled as raw emits, hiding compressor failures.

### C-06 — Certificate generation and verification are conflated in diagrams

- **Source and section:** `productSpec.md` §7 architecture and §13 system architecture; `buildPlan.md` §4 critical path and §7.1 independent verifier.
- **Conflicting statements:** Product diagrams contain a combined “Certificate generator/verifier” node, while the build plan requires a separate verifier that does not trust compressor flags.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Split claim generation from verification into separate packages, dependency roots, and runtime identities. The verifier may import shared schema and deterministic primitive libraries, but never compiler scoring, selection, or certificate-generation logic.
- **Reason:** Logical independence is impossible when evidence production and acceptance share decision state.
- **Impact if wrong:** A compressor bug could reproduce itself in the verifier and self-certify corruption.

### C-07 — “All certificate fields recomputable” conflicts with informational metadata

- **Source and section:** `productSpec.md` §12 certificate integrity; `buildPlan.md` §10 observability; required certificate fields in the Phase 0 task.
- **Conflicting statements:** The product says all certificate fields are independently recomputable, while timestamps, hardware, component declarations, and wall-clock timing are observations that cannot be derived from source and output alone.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Only fields labeled preservation claims are proof-bearing and independently recomputed. Informational fields are schema-validated and may be attested by the runtime, but never contribute to preservation status. Security-critical informational identifiers are checked against the verifier runtime/config rather than “recomputed” from content.
- **Reason:** This preserves the strong proof claim without pretending operational metadata is mathematical evidence.
- **Impact if wrong:** Non-reproducible metadata could invalidate valid proofs, or unverified metadata could be mistaken for proof.

### C-08 — Query is optional, but query hashing is mandatory

- **Source and section:** `productSpec.md` §1.2 and §5.2 inputs; §9.5 query binding; required architectural rules.
- **Conflicting statements:** The product accepts an optional query, yet every query-dependent certificate includes a query hash and query changes invalidate certificates. The no-query representation is unspecified.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Hash a canonical query envelope for every run: `{ "query": null }` when absent and `{ "query": <exact string> }` when present. Query presence is part of the hash domain.
- **Reason:** Optional input must not produce an optional security-critical binding.
- **Impact if wrong:** A query-agnostic artifact could be reused as if certified for a later query.

### C-09 — Discovery coverage cannot prove undiscovered obligations

- **Source and section:** `productSpec.md` §19.5, §20 first failure case, §24 Q12; `buildPlan.md` §6.2; required architectural rules.
- **Conflicting statements:** Certificate coverage is defined over discovered obligations, but both documents acknowledge that the extractor can miss decisive obligations. A 100% discovered-obligation ratio can therefore coexist with unknown real coverage.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Report `certificate_coverage` separately from `discovery_status`. `complete` preservation is prohibited unless all required analyzers completed, fixture/format applicability is known, and discovery status is `known`; otherwise completeness is `partial` or `unknown`.
- **Reason:** The denominator must not be presented as ground truth when discovery is incomplete.
- **Impact if wrong:** A certificate could confidently certify only the facts it happened to notice.

### C-10 — Source-map coordinates are called exact but are not defined

- **Source and section:** `productSpec.md` §7.2, §8.1, §12, §19.6; `buildPlan.md` §6.1 `SourceSpan` and §9.1.
- **Conflicting statements:** Exact byte/line/source mappings are required, while the proposed `SourceSpan.start/end` does not specify byte versus character units, bases, end inclusivity, encoding, columns, normalization lineage, or compressed-side coordinates.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Use the three-artifact, half-open coordinate contract in `docs/source-map-schema.md`, with explicit unit fields and hashes.
- **Reason:** Offset precision is not portable without coordinate conventions.
- **Impact if wrong:** Restoration can retrieve the wrong bytes, especially for Unicode, CRLF, tabs, or normalized JSON.

### C-11 — Source-map “coverage” mixes exact copying with synthesized content

- **Source and section:** `productSpec.md` §9.6 faithfulness policy, §12 source traceability, §19.6; required source-map support for synthesized summaries.
- **Conflicting statements:** Paraphrase is allowed for non-critical boilerplate, while retained claims are expected to map exactly to source and source-map coverage is treated as a single number.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Distinguish exact-copy coverage, lineage coverage, and protected-claim coverage. Synthesized spans have lineage but never count as exact-copy coverage and cannot carry exact protected values.
- **Reason:** Provenance and exact textual identity are different properties.
- **Impact if wrong:** A paraphrase could be counted as exact preservation.

### C-12 — Target tokenizer must be frozen, but the product is model-agnostic

- **Source and section:** `buildPlan.md` §5 Phase 0; `productSpec.md` §5.2, §12, §14.1, and §18.3.
- **Conflicting statements:** The schedule says to freeze “the target tokenizer,” while the product supports multiple target models and both `tiktoken` and Hugging Face tokenizers.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Freeze the tokenizer interface and full identity tuple, not one global tokenizer. Each run and benchmark configuration must choose an exact adapter ID and revision; counts from different identities are incomparable.
- **Reason:** Model-agnostic operation and reproducible counts both require explicit per-run selection.
- **Impact if wrong:** Reduction claims can drift when tokenizer versions or target models change.

### C-13 — The certificate lifecycle is circular

- **Source and section:** `productSpec.md` §5.4 steps 8–10 and §5.8; `buildPlan.md` §7.1–§7.3.
- **Conflicting statements:** The pipeline “generate[s] and verify[ies]” a certificate, then computes risk and recovery, but the certificate itself contains risk, final decision, and restored spans. It is unclear which artifact was verified.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Use an explicit lifecycle: compressor claim draft → independent verification observation → risk computation → recovery action → regenerated final artifact → final independent verification → sealed certificate. Every intermediate attempt is linked by hash and retained in the run record.
- **Reason:** A final certificate cannot precede the fields and artifact it certifies.
- **Impact if wrong:** A certificate may describe a pre-recovery output while being displayed beside a repaired output.

### C-14 — Raw and final compressed hashes are underspecified

- **Source and section:** `buildPlan.md` §6.1 `CompressionResult`, §8.4 result columns, §10 observability; `productSpec.md` §18.2.
- **Conflicting statements:** Raw and final outputs must remain distinct, but the minimum certificate has a single compressed hash.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** `compressed_context_hash` binds the final emitted artifact; `raw_compressed_context_hash` is required when recovery changed the raw output. Recovery events link both hashes.
- **Reason:** One hash cannot identify two different contexts.
- **Impact if wrong:** Fallback or restoration can erase evidence of the raw compressor failure.

### C-15 — Risk is both calibrated probability and allowed to be uncalibrated

- **Source and section:** `productSpec.md` §5.3 and §9.3; `buildPlan.md` §2.4, §6.7, §14 risk register, §17 definition of done.
- **Conflicting statements:** Product outputs call risk a calibrated probability, while the build plan permits an honestly labeled uncalibrated heuristic when data is insufficient.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** A risk score always carries `calibration_status` (`calibrated`, `uncalibrated`, or `not_available`). Only `calibrated` scores may be called probabilities or compared to probability thresholds.
- **Reason:** Numeric shape does not establish probabilistic meaning.
- **Impact if wrong:** An arbitrary heuristic could drive unsafe acceptance as if statistically calibrated.

### C-16 — The content-addressed source store conflicts with no persistence by default

- **Source and section:** `productSpec.md` §7 architecture, §9.5, §12 privacy, §22.4; `buildPlan.md` §2.1 and §6 implementation order.
- **Conflicting statements:** Restoration assumes a content-addressed store, while privacy says no context persistence by default.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** The source-store interface is required, but its default implementation is run-scoped memory with explicit destruction. Durable storage is opt-in, access-controlled, and policy-configured.
- **Reason:** Logical addressability does not require durable retention.
- **Impact if wrong:** Sensitive prompts could persist unexpectedly, or recovery could depend on a store that is absent.

### C-17 — JSON and logs share a compiler label despite different invariants

- **Source and section:** `productSpec.md` §7.1 and §13.1; `buildPlan.md` §2.1, §6.5; required architecture modules.
- **Conflicting statements:** Several sections combine JSON/logs as one compiler, but JSON schema/path/count rules differ materially from log template/severity/trace/causality rules.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Keep a shared `structured` compiler registry and utilities, but expose separate JSON and log analyzer/compiler plugins with independent invariant sets.
- **Reason:** Shared routing must not collapse distinct proof obligations.
- **Impact if wrong:** Log causality may be “verified” with JSON syntax checks, or JSON counts may be lost under log deduplication.

### C-18 — SIR is listed as an output but omitted from the public API response

- **Source and section:** `productSpec.md` §5.3 outputs and §11 FR-1 response; §11 FR-4 explain endpoint.
- **Conflicting statements:** The algorithmic output list includes the typed SIR, while the compression response example exposes certificate/provenance but not the SIR.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Treat SIR as an internal run artifact. It is available through authorized explain/report interfaces, not returned by default from compression endpoints.
- **Reason:** SIR may be large and may expose sensitive source structure; it is not required by the target model.
- **Impact if wrong:** API compatibility, data exposure, and token/cost expectations become unstable.

### C-19 — “Fail open” is semantically ambiguous

- **Source and section:** `productSpec.md` §12 and §20; required architectural rule “fail open to correctness.”
- **Conflicting statements:** In security terminology, “fail open” often means allow unsafe processing, but here it means provide larger or original context.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Define correctness-open behavior as “emit exact original/full context when policy permits; otherwise return an explicit error without emitting an uncertified shortened context.” It never means bypass role or access controls.
- **Reason:** Correctness fallback and authorization bypass must not be conflated.
- **Impact if wrong:** A safety slogan could create either semantic corruption or a security bypass.

### C-20 — File/path and multi-source hashing are underspecified

- **Source and section:** `productSpec.md` §8.1 provenance and §5.8 hashes; `buildPlan.md` §10 observability.
- **Conflicting statements:** Context may combine files, messages, JSON, and logs, but the certificate provides one source hash without defining ordering, path normalization, or per-source hashes.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Hash every immutable source separately, then hash a canonical ordered source manifest to obtain `source_hash`. Manifest order is input order; stable source IDs, media types, byte lengths, and hashes are included.
- **Reason:** Concatenation without framing is ambiguous and vulnerable to reorder/collision-of-structure errors.
- **Impact if wrong:** The same aggregate text with different boundaries or authority roles could share a misleading source binding.

### C-21 — Status and action are mixed

- **Source and section:** `productSpec.md` §11 FR-1 (`status: certified`, `decision: emit`); `buildPlan.md` §8.4 (`accepted`, `fallback`, `status`, `error`).
- **Conflicting statements:** Certification status, verification result, acceptance, and recovery action appear as overlapping fields without a state model.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Separate `verification_status` (`passed`, `failed`, `indeterminate`), `selected_action` (four allowed actions), and benchmark acceptance (a report-layer property, not certificate truth).
- **Reason:** A fallback artifact can pass verification but must still reveal that the raw compressor failed.
- **Impact if wrong:** Reports may count repaired/fallback cases as raw certified successes.

### C-22 — Structured counts are named both source obligations and compiler metadata

- **Source and section:** `productSpec.md` §7.1 structured compiler and §8.1 structured obligations; `buildPlan.md` §6.5 and §7.1.
- **Conflicting statements:** Row counts, schema counts, and anomaly counts may be discovered by the compressor, yet the verifier is required to recompute them independently. The authoritative parser is unspecified.
- **Proposed resolution:** **[PROPOSED PROJECT DECISION]** Compressor counts are claims only. The verifier reparses original and emitted structured artifacts using its declared parser/version and records its own observations; parser disagreement yields `indeterminate` and recovery.
- **Reason:** Copying claimed counts is not verification.
- **Impact if wrong:** A compressor sampling/counting bug could self-certify missing rows.

## Unresolved questions

These choices are intentionally not guessed in Phase 0. They do not block Phase 1 scaffolding unless stated otherwise.

Approval-gate status: `PHASE_0_APPROVAL.md` classifies every item below. That approval record resolves the Phase 1 TypeScript boundary and repository publication location for public JSON Schemas, and assigns an owner/latest decision point to every remaining deferral. This historical list is retained so the frozen contract is not silently rewritten.

1. Which exact target tokenizer identities and revisions will be used for the final demo and benchmark configurations?
2. Which safe/balanced/aggressive risk thresholds will be selected after calibration evidence exists?
3. Will logistic regression or isotonic regression be used for the first genuinely calibrated risk model?
4. Which HELMET, LongBench v2, and RULER slices are feasible and license-compatible for the frozen evaluation?
5. Is Headroom reproducible in the submission environment, or limited to a source-backed qualitative comparison?
6. Does DAC fit the remaining benchmark budget?
7. What is the final size and release scope of `ContextProofBench`?
8. Which target-model families and hosted provider, if any, will be used?
9. What policy enables durable source storage, retention duration, and retrieval authorization?
10. What analyzer evidence is sufficient to mark discovery coverage `known` for each content type?
11. What conservative cutoff or unsupported-feature list triggers broader restoration for Python reflection/dynamic dispatch?
12. Whether later versions support TypeScript; v1 contracts are Python-code specific.
13. Whether selective NLI or differential probes are required at the certified operating point; they cannot replace structural checks.
14. The external JSON Schema publication URI and registry location. Local schema identifiers are frozen; hosting is not.
15. Final product name and public category wording remain product decisions, not engineering-contract blockers.

## Acceptance criteria

Phase 0 is accepted only if all of the following are true:

- All six required documentation files exist.
- `productSpec.md` and `buildPlan.md` are byte-identical to their `main` versions.
- Every required module has responsibility, inputs, outputs, dependencies, forbidden responsibilities, and failure behavior.
- Compressor/verifier independence and the verifier's recomputation duty are explicit and testable.
- Every required protected obligation and relation class has all nine invariant attributes.
- The certificate contract is versioned, defines the four actions, separates claims from observations, marks informational and security-critical fields, and contains a complete valid JSON example that is explicitly synthetic.
- The source-map contract defines exact coordinate semantics, bidirectional lineage, staleness checks, and all five requested JSON mapping examples.
- Phase 1 has an exact allowlist, interfaces, schemas, acceptance tests, non-goals, and exit commands and contains no semantic/compression implementation.
- Every new engineering choice is labeled **[PROPOSED PROJECT DECISION]**.
- No unsupported benchmark or performance result is introduced.
- Raw, certified, and end-to-end result identities remain distinct in every relevant contract.
- Markdown passes `git diff --check`.
- Review finds no unresolved internal contradiction outside the explicitly registered questions/issues.

## Exit gate

Phase 0 exits when:

1. The six documents pass the acceptance criteria and cross-reference one another consistently.
2. The branch contains only the intended documentation changes.
3. The source specification hashes still match their pre-phase values.
4. The contradiction register has an explicit owner decision path: accept each proposed resolution or amend it before Phase 1 implementation.
5. The commit `docs: freeze TraceFold proof contract` is pushed to `origin/phase/0-proof-contract`.

Exit from Phase 0 authorizes review of Phase 1 scaffolding. It does not authorize Phase 1 implementation, merging to `main`, or any compressor/API/UI/benchmark work.
