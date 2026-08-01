# TraceFold Architecture Contract

Status: Phase 0 freeze

Related contracts: `PHASE_0_CONTRACT.md`, `invariants.md`, `certificate-schema.md`, `source-map-schema.md`

This document defines logical module boundaries. It does not prescribe process topology, deployment count, or implementation language beyond the Python-first direction in the source specifications.

Source basis: `productSpec.md` §§5, 7–9, 11–13, 18, and 20 and `buildPlan.md` §§1–4, 6–7, and 10–11. **[PROPOSED PROJECT DECISION]** Detailed dependency restrictions, typed failure states, and boundary refinements not stated verbatim in those sections are proposed project decisions for this freeze.

## Architectural principles

1. Prefer deterministic, local verification.
2. No LLM may certify its own compression output.
3. Every preservation claim is independently recomputable from bound artifacts and versioned policy.
4. Exact protected values are copied exactly; they are never paraphrased.
5. Relations and evidence paths are protected, not merely isolated tokens.
6. Query-dependent artifacts bind a canonical query hash, including the explicit null-query envelope.
7. Unknown discovery coverage prohibits a complete-preservation claim.
8. Raw, certified, and end-to-end artifacts and measurements remain distinct.
9. Recovery never hides the raw failure that triggered it.
10. Source mappings remain valid and hash-bound across normalization.
11. Dense or incompressible input may expand or use full context.
12. Correctness-open failure means full exact context when policy permits, otherwise an explicit error; it never means authorization bypass.

## End-to-end dataflow

```text
caller
  -> gateway
  -> normalizer
  -> content router
  -> typed analyzers
  -> semantic IR + obligation ledger + dependency graph
  -> budget allocator
  -> content-specific compiler
  -> source-map generator
  -> certificate claim generator
  -> independent verifier
  -> risk calibrator
  -> recovery controller
       -> [restore / expand / full fallback -> re-map -> re-claim -> re-verify]
  -> target-model adapter

immutable run artifacts
  -> benchmark harness -> reporting layer -> demo UI
```

**[PROPOSED PROJECT DECISION]** The certificate lifecycle is two-stage: an untrusted claim draft is generated for a specific artifact, then the verifier emits independent observations. Risk and recovery can change the artifact. The final certificate is sealed only after the final artifact is independently reverified.

## Trust boundaries

### Compression trust domain

The normalizer, analyzers, semantic IR, ledger, graph, allocator, compilers, source-map generator, and certificate generator form the compression trust domain. Their outputs are claims, candidates, or lineage data. None is sufficient to certify preservation.

### Verification trust domain

The independent verifier is a separate logical component. It receives the immutable compression request, original artifacts, query envelope, emitted context, source map, and certificate claim draft and MUST:

- recompute hashes and token counts;
- independently rediscover applicable obligations and relations;
- reparse structured/code artifacts using declared verifier components;
- validate source mappings against artifact bytes;
- compare its observations to compressor claims;
- emit `passed`, `failed`, or `indeterminate` without consulting compressor scores.

It MUST NOT import the selector, budget allocator, compilers, risk model, recovery policy, or certificate-generator pass/fail logic. **[PROPOSED PROJECT DECISION]** Shared code is limited to schema types, canonical serialization, cryptographic hashing primitives, tokenizer interfaces, and parser adapters whose outputs the verifier independently invokes.

### Policy and recovery trust domain

The risk calibrator consumes verifier observations and versioned non-proof features. The recovery controller applies policy. Neither may rewrite verifier evidence. The controller can request a new candidate, but each changed artifact re-enters verification.

### Presentation trust domain

The reporting layer and demo UI are read-only consumers of immutable run artifacts. They MUST NOT calculate replacement metrics, rewrite statuses, or combine raw and recovered results.

## Shared artifact rules

- Artifact exchange uses versioned Pydantic/domain schemas and canonical JSON where serialized.
- Original bytes, normalized bytes, raw compressed bytes, and final emitted bytes have distinct lifecycle identifiers. Original and normalized artifacts use distinct hash domains; raw, restored, and final contexts use the shared `tracefold:context-artifact:1` domain so equal hashes prove equal bytes while identifiers preserve lifecycle role. **[APPROVAL DECISION A-01]**
- Run IDs correlate artifacts but are not content identity.
- All lists whose order affects hashes define an explicit order.
- Failure objects contain stable machine codes and human-readable messages without secret contents.
- Recovery records are compare-and-append, sequence-checked, event-hash-chained, and rebound by a verifier-recomputed history hash; resolved raw failures remain immutable history. **[APPROVAL DECISION A-02]**
- **[PROPOSED PROJECT DECISION]** A module returns either a typed success artifact or a typed failure; `None`, partial dicts, and silent best-effort success are forbidden at trust boundaries.

## Module contracts

### Gateway

- **Responsibility:** Accept CLI/HTTP/library requests, authenticate/authorize where configured, enforce input-size and request-shape policy, assign or validate run correlation, and return the final result envelope.
- **Inputs:** Exact messages/source blocks, optional query, requested token budget or reduction, policy mode, content hint, tokenizer identity, output flags, caller identity/policy context.
- **Outputs:** A normalized internal request envelope; later, a response containing final context, final certificate, report references, and explicit error/fallback state.
- **Dependencies:** Domain schemas, run-ID service, normalizer, recovery orchestration facade, logging. It may call adapters only through the orchestrator contract.
- **Forbidden responsibilities:** Parsing semantic obligations, selecting spans, generating proof evidence, computing risk, certifying output, or presenting benchmark results.
- **Failure behavior:** Reject malformed/unauthorized/oversized input explicitly. Never truncate input silently. If downstream correctness fallback is allowed, return full context plus recorded action; otherwise return a typed error.

### Normalizer

- **Responsibility:** Convert the request into deterministic typed source blocks while preserving authority roles, boundaries, input order, exact original bytes, and normalization lineage.
- **Inputs:** Gateway request envelope and immutable original source artifacts.
- **Outputs:** Normalized source manifest, normalized artifacts, role/scope metadata, normalization events, and original-to-normalized mapping anchors.
- **Dependencies:** Source-map schema/primitives, encoding detection policy, canonical source-manifest serialization.
- **Forbidden responsibilities:** Dropping content for budget reasons, interpreting untrusted text as authority, extracting semantic obligations, choosing a compiler, or accepting lossy repair.
- **Failure behavior:** On undecodable/malformed input, preserve raw bytes and report a parser warning. If safe normalized text cannot be produced, mark analysis unavailable and force correctness fallback or explicit error.

### Content router

- **Responsibility:** Classify each normalized block into supported content types and select applicable analyzer/compiler plugins without changing content.
- **Inputs:** Normalized manifest, optional content hint, media types, file suffixes, parse probes.
- **Outputs:** Routing plan with per-block type, confidence/evidence, required analyzers, and fallback route.
- **Dependencies:** Plugin registry and deterministic sniffers/parsers.
- **Forbidden responsibilities:** Compression, semantic importance scoring, certificate acceptance, or overriding explicit role boundaries.
- **Failure behavior:** Mixed or uncertain content is split only at source-mapped boundaries. Unknown content routes to the conservative document path with `discovery_status=unknown`; it cannot receive a complete-preservation claim.

### Typed analyzers

- **Responsibility:** Produce typed semantic units, protected-obligation candidates, relation candidates, structural facts, parser warnings, and analyzer coverage declarations for each content type.
- **Inputs:** Normalized artifacts, routing plan, query envelope for relevance annotations only, analyzer configuration.
- **Outputs:** Analyzer observations with source spans, confidence/applicability, parser/version identity, and discovery status.
- **Dependencies:** Deterministic regex/grammar parsers, JSON parser, Python parser, dialogue/document segmenter; optional model-based signals are isolated and labeled.
- **Forbidden responsibilities:** Deleting or paraphrasing content, deciding preservation success, trusting prior analyzer claims, controlling budget, or calling target models for certification.
- **Failure behavior:** Emit partial observations plus explicit warnings and `unknown`/`incomplete` coverage. Analyzer failure raises risk and forces expansion/fallback; it never produces an empty “complete” ledger.

**[PROPOSED PROJECT DECISION]** JSON and log analysis are separate plugins even when they share structured utilities. This preserves distinct path/count versus severity/trace/causality evidence.

### Semantic intermediate representation

- **Responsibility:** Provide the immutable typed representation of semantic units, aliases, structural nodes, source spans, and analyzer provenance used by later compression components.
- **Inputs:** Normalized manifest and typed analyzer observations.
- **Outputs:** Versioned SIR graph input: nodes, typed attributes, source references, analyzer provenance, and unresolved references.
- **Dependencies:** Domain schemas and source-map identifiers only.
- **Forbidden responsibilities:** Scoring, budget allocation, text generation, verification, persistence policy, or mutating source artifacts.
- **Failure behavior:** Reject dangling required source references or invalid schema. Preserve unresolved semantic references explicitly; never coerce them to resolved.

### Protected-obligation ledger

- **Responsibility:** Canonically record every discovered protected obligation and relation, hardness, exact value representation, owners/scopes, source locations, detector provenance, and required verifier rule.
- **Inputs:** SIR nodes/relations and the invariant registry from `invariants.md`.
- **Outputs:** Immutable obligation manifest with stable IDs, class counts, discovery status, and conflicts/duplicates.
- **Dependencies:** SIR, invariant registry, canonical ID/hash utilities.
- **Forbidden responsibilities:** Claiming true source completeness, marking compressor output preserved, assigning compression utility, or removing duplicate obligations without retaining alias/provenance links.
- **Failure behavior:** Ledger conflicts or missing required fields make certificate status `indeterminate`; hard obligations remain seeded for preservation and trigger recovery if unresolvable.

### Semantic dependency graph

- **Responsibility:** Represent typed semantic and structural dependencies, including required relation classes, evidence paths, contradictions, supersession, and unresolved edges.
- **Inputs:** SIR and protected-obligation ledger.
- **Outputs:** Immutable typed graph with node/edge IDs, source provenance, required-path constraints, and unresolved-edge records.
- **Dependencies:** SIR, ledger, graph data structures.
- **Forbidden responsibilities:** Treating statistical centrality as proof, choosing the final budget, altering obligations, or asserting that a retained graph implies downstream-answer equivalence.
- **Failure behavior:** Broken or ambiguous hard relations are explicit graph failures. Selector may request broader context, but certification remains failed/indeterminate until independently verified.

### Budget allocator

- **Responsibility:** Convert the requested reduction or token budget into per-block/per-compiler budgets using content type, query relevance, hard-obligation cost, and risk policy.
- **Inputs:** Tokenizer identity, original token observation, requested budget/reduction, SIR/ledger/graph summaries, policy mode.
- **Outputs:** Versioned allocation plan with hard minimum, assigned budgets, unmet-target reason, and deterministic tie-breaks.
- **Dependencies:** Tokenizer abstraction, ledger/graph summaries, policy configuration.
- **Forbidden responsibilities:** Dropping hard obligations, certifying safety, falsifying requested/achieved reduction, or forcing every input to meet 70% reduction.
- **Failure behavior:** If hard minimum exceeds requested budget, report infeasibility and request `expand_budget` or `full_fallback`; never underfund hard invariants silently.

### Content-specific compilers

- **Responsibility:** Produce raw compressed candidates for document/dialogue, JSON, logs, and Python according to the allocation plan while preserving required exact spans and relation-connected context.
- **Inputs:** Normalized artifacts, SIR, ledger, graph, allocation plan, query envelope, tokenizer.
- **Outputs:** Raw compressed artifact, transform manifest, selected/deleted/synthesized span records, compiler warnings, and claimed obligation retention.
- **Dependencies:** Analyzer/SIR artifacts, source-map primitives, tokenizer, compiler plugin registry.
- **Forbidden responsibilities:** Self-certification, changing original source, calling a target LLM to decide proof, hiding deleted spans, or labeling selective loss as lossless.
- **Failure behavior:** Parse/compile failure yields no certified short artifact. Emit a typed failure and allow the recovery controller to expand or fall back.

Compiler-specific minimum boundaries:

- Document/dialogue preserves role boundaries, corrections, commitments, ownership, and connected evidence.
- JSON preserves parse validity, paths, schema/count semantics, anomalous rows, and exact protected values.
- Logs preserve event identity, timestamps, severity transitions, trace/request IDs, anomalies, and causal neighbors.
- Python preserves parseability claims only when independently reparsed and protects definitions, imports, calls, constants, guards, and exception paths.

### Source-map generator

- **Responsibility:** Build exact lineage among original, normalized, raw compressed, restored, and final emitted artifacts.
- **Inputs:** Normalization events, compiler transform manifest, recovery events, immutable artifact bytes and metadata.
- **Outputs:** Versioned source map with artifact hashes, stable IDs, coordinate sets, forward/reverse indexes, deletion/synthesis/restoration records, and coverage observations.
- **Dependencies:** `source-map-schema.md`, canonical serialization, hashing primitives.
- **Forbidden responsibilities:** Inventing missing provenance, treating synthesized text as exact copy, deciding semantic preservation, or updating a map without rebinding hashes.
- **Failure behavior:** Any coordinate/hash inconsistency marks the map stale and blocks certification. Recovery uses original bytes directly, never a stale map.

### Certificate generator

- **Responsibility:** Assemble compressor claims and references into an untrusted certificate draft for one exact candidate artifact; after final verification, canonically package the immutable claim, verifier-observation, risk, and action objects without recalculating or modifying them.
- **Inputs:** Run/source/query/artifact identities, ledger claims, claimed relation results, source map, parser warnings, component identities, raw/final linkage.
- **Outputs:** Schema-valid claim draft and, after orchestration supplies all independently owned records, a canonical final certificate with no verifier-owned observations fabricated.
- **Dependencies:** Certificate schema, canonical serialization, hashes, compressor artifacts, and public immutable verifier/risk/action result schemas (never their implementation internals).
- **Forbidden responsibilities:** Setting independent verifier observations, declaring final verification success, suppressing failed invariants, or selecting risk/action based on its own claims alone.
- **Failure behavior:** Schema/canonicalization failure prevents certification and triggers explicit recovery/error.

### Independent verifier

- **Responsibility:** Recompute preservation evidence from bound inputs; validate hashes, counts, relations, structure, source-map lineage, and completeness constraints; issue independent observations.
- **Inputs:** Canonical compression request envelope, original source manifest/artifacts, query envelope, final candidate artifact, source map, claim draft, verifier policy, exact component versions.
- **Outputs:** Verification observations, rediscovered obligation/relation counts, failed invariants, parser warnings, map coverage/staleness, and `passed`/`failed`/`indeterminate`.
- **Dependencies:** Shared schemas/hash/tokenizer interfaces; independent detector/parser implementations or independently invoked deterministic parsers; invariant registry.
- **Forbidden responsibilities:** Importing compiler scoring/selection logic, copying compressor `passed` flags, using an LLM that generated the compression as certifier, repairing output, selecting budget, or hiding unknown discovery.
- **Failure behavior:** Internal error, parser disagreement, unavailable required analyzer, stale map, or unknown critical coverage produces `indeterminate`, which cannot lead to raw `emit` under certified policy.

### Risk calibrator

- **Responsibility:** Estimate answer-change risk from verifier observations and versioned features, while declaring whether the score is calibrated.
- **Inputs:** Independent verifier output, compression ratio, content type, parser uncertainty, graph breakage observations, recovery history, calibrator ID/version.
- **Outputs:** Score, calibration status, feature-manifest hash, recomputation result, model/version identity, and warnings.
- **Dependencies:** Frozen calibrator artifact and feature extractor; verifier output.
- **Forbidden responsibilities:** Overriding failed invariants, calling an uncalibrated score a probability, certifying its own input, or rewriting raw results.
- **Failure behavior:** Missing/invalid calibrator produces `not_available` or `uncalibrated`. Policy must expand/fallback where calibrated risk is required.

### Recovery controller

- **Responsibility:** Apply deterministic policy to verifier/risk outcomes and choose exactly one of `emit`, `restore_spans`, `expand_budget`, or `full_fallback`; orchestrate iterative reverification.
- **Inputs:** Verification observations, risk result, allocation plan, source map, exact source store, policy thresholds, prior attempts.
- **Outputs:** Selected action, recovery event ledger, new candidate requests, final emitted artifact, fallback reason, and raw/final linkage.
- **Dependencies:** Verifier facade, budget allocator/compilers through orchestration interfaces, source store, policy configuration.
- **Forbidden responsibilities:** Editing verifier evidence, declaring a repaired artifact valid without reverification, removing prior failure records, or reducing restored context within the same recovery chain.
- **Failure behavior:** Exhaustion, unavailable exact spans, or repeated indeterminate verification triggers `full_fallback` when authorized; otherwise explicit error with no shortened uncertified context.

### Target-model adapter

- **Responsibility:** Send full or final context to a declared target model with identical frozen settings where comparisons are requested; normalize provider responses and usage.
- **Inputs:** Exact prompt envelope, final/full context selector, target model/tokenizer/config identity, credentials via runtime policy.
- **Outputs:** Target response, provider usage, timing/cost observations, model revision, and errors.
- **Dependencies:** Provider/local model clients, tokenizer identity, gateway policy.
- **Forbidden responsibilities:** Compression, certification, modifying prompts differently across paired runs, reading credentials from committed files, or hiding provider failures.
- **Failure behavior:** Record explicit adapter failure. Retries are idempotent and policy-limited. Adapter failure cannot change preservation status.

### Benchmark harness

- **Responsibility:** Run frozen examples/methods at matched budgets and settings; preserve per-example raw, certified, and end-to-end artifacts and metrics.
- **Inputs:** Frozen dataset adapters/splits, method configs, target adapter configs, seeds, tokenizer identity, run manifests.
- **Outputs:** Immutable per-example records, failure ledger, aggregate inputs, and reproducibility metadata.
- **Dependencies:** Public orchestration/adapter interfaces, scorers, artifact store; never internal UI state.
- **Forbidden responsibilities:** Editing outputs, dropping failures without status, substituting fallback scores for raw scores, inventing competitor results, or using unmatched budgets/settings.
- **Failure behavior:** Failed/unavailable methods remain explicit rows. Partial runs are marked partial; they are not silently excluded.

### Reporting layer

- **Responsibility:** Compute transparent aggregates and tables/curves from immutable benchmark/run records and render provenance-aware reports.
- **Inputs:** Validated run records, metric definitions, grouping/config manifest.
- **Outputs:** Raw/certified/end-to-end tables, per-format/per-class metrics, risk-coverage and retention-reduction views, economics, warnings, and traceable report metadata.
- **Dependencies:** Benchmark artifacts, deterministic metric library, schema validators.
- **Forbidden responsibilities:** Running compression, altering source records, filling missing results, merging result views, or presenting targets as achieved measurements.
- **Failure behavior:** Invalid/missing inputs produce visible incomplete reports with excluded-row reasons; no placeholder or fabricated cells.

### Demo UI

- **Responsibility:** Present request controls, original/raw/final contexts, verification failures, recovery events, exact source lineage, and frozen report results.
- **Inputs:** Gateway responses, explain/report endpoints, immutable committed demo artifacts.
- **Outputs:** Human-readable visualization and user-triggered requests only.
- **Dependencies:** Gateway and reporting APIs; no direct database mutation.
- **Forbidden responsibilities:** Computing certificates or metrics, changing action/status, hiding raw failures/fallback, exposing secrets, or displaying animated/fabricated results.
- **Failure behavior:** Clearly distinguish API failure, unavailable report, and uncertified result. Fall back to committed deterministic artifacts only when visibly labeled.

## Dependency constraints

Allowed high-level dependency direction:

```text
schemas/hash/tokenizer/source primitives
  <- normalizer/router/analyzers
  <- SIR/ledger/graph
  <- allocator/compilers
  <- claim generator

schemas/hash/tokenizer/verifier parsers/invariant registry
  <- independent verifier

verifier observations + policy
  <- risk calibrator
  <- recovery controller

orchestration public interfaces
  <- gateway/CLI/benchmark
  <- reporting
  <- demo UI
```

Forbidden dependency edges:

- verifier → compiler, selector, allocator, recovery, reporting, or UI;
- certificate generator → verifier internals;
- compiler → verifier acceptance result;
- reporting/UI → mutable run state;
- target adapter → compressor or certificate generator;
- any proof component → a model-generated self-assessment as authoritative truth.

## Failure-state contract

Every stage uses one of these states:

- `ok`: complete typed output for the declared applicability.
- `warning`: complete output plus non-critical warning; warning remains visible downstream.
- `incomplete`: partial output and unknown discovery; complete certification prohibited.
- `failed`: no valid output for the stage.

The independent verification state is separately `passed`, `failed`, or `indeterminate`. Only `passed` may support certified raw `emit`; policy may still choose a larger context. `failed` or `indeterminate` moves toward restoration, budget expansion, full fallback, or explicit error.

## Architecture-invalidating risks

- Shared compressor/verifier logic reproduces the same semantic bug.
- Obligation discovery coverage is mistaken for true source coverage.
- Normalization loses byte lineage, making exact restoration impossible.
- Canonicalization/tokenizer drift changes hashes or reductions across components.
- A probabilistic or model-generated signal becomes authoritative proof.
- Recovery overwrites raw artifacts or reporting combines result views.
- Structured/code parsers disagree without producing `indeterminate`.
- Durable source storage violates privacy/access policy.
- Dense input is forced to fit an unsafe budget.
