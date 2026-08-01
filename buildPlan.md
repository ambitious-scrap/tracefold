# TraceFold Build Plan

> **Project:** Innova Hack Chapter 1, Round 2  
> **Problem Statement:** Gen AI PS 2, Ultra-Low Resource LLM Context Compression Engine  
> **Companion document:** `productSpec.md`  
> **Plan type:** Deadline-aware critical-path implementation plan  
> **Planning origin:** 1 August 2026, approximately 12:00 IST  
> **Research revision:** 1 August 2026, 12:36 IST, incorporating `deep-research-report.md`

---

## 0. Planning basis

### Official constraints

**[OFFICIAL]** The official PDF states:

- Round 2 begins 1 August 2026 at 11:00 AM.
- Submission closes 2 August 2026 at 6:00 PM IST.
- The submission must include a deployed project URL.
- A public Drive link must include the repository and a 6 to 7 slide presentation.
- A 5-minute explanatory video is optional.
- No commits, merges, or code changes are permitted after the deadline.
- The named organizer collaborator must be added to the GitHub repository before submission.

Sources: official PDF, pages 1, 17, and 18.

### Strategic rule

The choice of PS 2 remains based on maximum winning ceiling. This build plan is allowed to be execution-aware because it governs delivery, not problem selection.

### Plan assumptions

- **[ASSUMPTION]** Work begins near 12:00 IST on 1 August.
- **[ASSUMPTION]** Team size is unknown. Work is organized into role lanes that can be combined.
- **[ASSUMPTION]** At least one machine can run lightweight embedding and NLI models.
- **[ASSUMPTION]** A hosted LLM API may be available, but the demo must have a local fallback.
- **[ASSUMPTION]** The trained variant is a stretch goal. The training-free system is the submission-critical product.

---

## 1. Build objective

Deliver a working TraceFold proof-carrying context compiler that:

1. Accepts long documents/dialogue, JSON/logs, or Python code plus a query.
2. Produces a compressed context under a requested token budget.
3. Builds a typed semantic IR, protected-obligation ledger, and source map.
4. Preserves exact semantic relations, not merely important tokens.
5. Generates an independently verifiable preservation certificate.
6. Calibrates semantic-loss risk on a frozen validation set.
7. Restores exact source spans, expands the budget, or falls back when unsafe.
8. Sends full and compressed contexts to the same target model.
9. Reports raw, certified, and end-to-end results separately.
10. Benchmarks against strong academic and product competitors.
11. Displays token reduction, task retention, certificate status, risk, latency, net cost, and provenance.
12. Is deployed and presentation-ready before the submission freeze.

## 2. Scope control

### 2.1 P0, must ship

- Three minimal compilers: documents/dialogue, structured JSON/logs, and Python code.
- Role-aware normalization and prompt-injection boundary preservation.
- Typed protected-obligation ledger, including relation-level checks.
- Semantic dependency graph and greedy CPRGC selector.
- Exact source map and content-addressed source store.
- Machine-verifiable certificate schema and independent verifier.
- Risk score with logistic or isotonic calibration on `ContextProofBench` validation cases.
- Exact-span restoration and full-context fallback.
- Full versus compressed target-model comparison.
- Benchmark harness with matched budgets and three result views: raw, certified, end to end.
- Baselines: full context, truncation, embedding Top-K, LLMLingua-2, and Headroom where runnable.
- Format-specific comparisons: compact JSON/TOON-style encoding and Repomix-style code skeleton.
- A deterministic `ContextProofBench` slice with at least 30 corruption cases.
- One real-world benchmark slice from RULER/LongBench/HELMET.
- Deployed UI showing certificate failure and repair.
- 6 to 7 slide deck and backup recording.

### 2.2 P1, ship only after P0 is stable

- DAC and Selective Context baselines.
- Selective differential answer probes.
- Larger HELMET/LongBench/RULER suite.
- Risk-coverage and Pareto dashboards.
- Exact span retrieval for follow-up query changes.
- NLI contradiction verifier.
- Multi-hop path verifier.
- Multiple target-model families.

### 2.3 P2, stretch

- Distilled trained retention/risk model.
- TypeScript code compiler.
- SWE-bench subset.
- Full public ContextProofBench release.
- Exact OR-Tools selector for research comparison.
- Custom React front end.

### 2.4 Explicit cuts

Cut these first if the schedule slips:

1. Custom React UI.
2. Trained compressor.
3. TypeScript support.
4. SWE-bench.
5. DAC and Selective Context installations.
6. Multiple hosted providers.
7. Abstractive compaction.

Do not cut:

- certificate and independent verification,
- source map,
- relation-level protected obligations,
- risk calibration or an honest “uncalibrated” label,
- exact-span restoration/fallback,
- raw versus certified versus end-to-end reporting,
- Headroom and LLMLingua-2 competitive framing,
- end-to-end latency and net-cost accounting,
- deployment and submission checks.

## 3. Team workstreams

| Lane | Responsibilities | Can be combined with |
|---|---|---|
| Algorithm | Segmentation, anchors, graph, selector, verifier | Evaluation |
| Platform | API, target adapters, run schemas, persistence | Algorithm |
| Evaluation | Datasets, baselines, metrics, reports, ablations | Algorithm |
| Demo | UI, visualizations, golden examples, deployment | Pitch |
| Pitch and submission | Slides, video, README, links, repository compliance | Demo |

If only two people are available:

- Person A: algorithm + evaluation.
- Person B: platform + demo + pitch.

If three people are available:

- A: algorithm.
- B: evaluation and baselines.
- C: platform, demo, and submission.

---

## 4. Critical path

```mermaid
flowchart LR
    A[Schemas + tokenizer] --> B[Typed obligations + source map]
    B --> C[Document/JSON-log/Python compilers]
    C --> D[Semantic graph + selector]
    D --> E[Certificate generator + independent verifier]
    E --> F[Risk calibration]
    F --> G[Restoration/fallback]
    G --> H[Target-model comparison]
    H --> I[Matched-budget benchmark]
    I --> J[Demo: certificate failure and repair]
    J --> K[Slides, deploy, submit]
```

The proof must be real before visual polish begins. A router and dashboard without a recomputable certificate is not a viable winning build.

## 5. Time-boxed execution schedule

Times are in IST and should be shifted by elapsed time while preserving order.

## Phase 0: Lock the proof contract

**1 Aug, 12:36 to 13:15**

- Freeze certificate schema, source-map schema, and four decisions: `emit`, `restore_spans`, `expand_budget`, `full_fallback`.
- Freeze target tokenizer and token counter.
- Create `ContextProofBench` schema and 10 initial adversarial cases.
- Commit product and build specifications.

**Exit:** a certificate fixture can be independently verified from a source fixture.

## Phase 1: Typed obligations and source map

**1 Aug, 13:15 to 15:15**

- Parse role boundaries, documents, JSON/logs, and Python.
- Extract identifiers, quantities/units, negation, quantifiers, permissions, conditions, exceptions, dates, code obligations, JSON paths, and log events.
- Create relation records: value-owner, rule-exception, condition-consequence, code dependency, temporal order, trace causality.
- Emit exact source spans and content hashes.

**Exit:** 20 adversarial fixtures reach 100% detected protected-class recall on the fixture labels.

**Commit:** `feat: typed obligations and exact source mapping`

## Phase 2: Three minimal compilers

**1 Aug, 15:15 to 18:15**

- Document/dialogue: segmentation, deduplication, query relevance, role/correction protection.
- JSON/logs: compact schema, template deduplication, anomaly/trace preservation, row counts and paths.
- Python: Tree-sitter parse, imports/signatures/constants, query-relevant bodies, branch and exception preservation.
- Keep output readable and syntactically valid.

**Exit:** each compiler achieves a prepared >70% reduction case without losing labeled obligations.

**Commit:** `feat: document structured and python compilers`

## Phase 3: Graph selector and certificate

**1 Aug, 18:15 to 21:00**

- Build sparse semantic/dependency graph.
- Add bridge and anomaly utility.
- Implement greedy CPRGC selector.
- Generate certificate with hashes, class counts, relation checks, source coverage, failures, and decision.
- Implement a separate verifier module that recomputes checks.

**Exit:** a deliberately corrupted compressed artifact fails certificate verification.

**Commit:** `feat: proof carrying compression certificate`

## Phase 4: Risk calibration and recovery

**1 Aug, 21:00 to 23:00**

- Expand `ContextProofBench` to at least 30 labeled cases.
- Extract risk features from checks and graph state.
- Fit logistic or isotonic calibrator on a frozen validation split.
- Add exact-span restoration, budget expansion, and full fallback.
- Record raw and post-recovery outputs separately.

**Exit:** Brier score/ECE and a risk-coverage table are generated; the 85% demo case restores only the needed span.

**Commit:** `feat: calibrated risk and exact span recovery`

## Phase 5: Target adapters and economics

**1 Aug, 23:00 to 2 Aug, 00:45**

- Implement local and optional hosted target adapters.
- Run full/compressed with identical settings.
- Record input/output tokens, compression, verification, target, restoration, and fallback time/cost.
- Add short-prompt bypass.

**Exit:** `/v1/compare` returns full, raw, certified, and end-to-end results with certificate and economics.

**Commit:** `feat: full proof aware inference comparison`

## Phase 6: Baselines and benchmark harness

**2 Aug, 00:45 to 03:30**

Guaranteed baselines:

1. Full context.
2. Head/tail/head-plus-tail truncation.
3. Embedding Top-K.
4. LLMLingua-2 or documented installation failure.
5. Compact JSON and TOON-style structured encoding.
6. Repomix-style Python skeleton.

Competitor priority:

- Run Headroom if reproducible within the timebox.
- If not, keep a source-backed feature comparison and never invent benchmark numbers.
- DAC is P1.

Harness requirements:

- Matched target-token budgets.
- Per-example JSONL.
- Raw/certified/end-to-end outputs.
- Per-class certificate results.
- Net cost and end-to-end latency.

**Exit:** at least 50 honest paired examples or the largest reproducible set time allows.

**Commit:** `test: proof aware matched budget benchmark`

## Phase 7: Overnight runs

**2 Aug, 03:30 to 08:00**

- Run frozen `ContextProofBench`, RULER, and selected LongBench/HELMET tasks.
- Run 30%, 50%, 70%, 80%, and 90% reduction settings where feasible.
- Produce retention-reduction and risk-coverage tables.
- Save logs, partial outputs, and failure ledger.

**Exit:** no manual edits to benchmark outputs are needed.

## Phase 8: Result triage and ablations

**2 Aug, 08:00 to 10:30**

- Validate artifacts and remove failed runs transparently.
- Run essential ablations: no protected ledger, no relation checks, no certificate, no calibration, no fallback, LLMLingua-only selector.
- Freeze the operating threshold.
- Select headline result only from committed report data.

**Exit:** credible table, risk-coverage curve, and at least three positive ablations.

## Phase 9: Demo application

**2 Aug, 10:30 to 13:00**

UI must show:

- original and compiled context,
- full, competitor, and TraceFold answers,
- certificate fields and failed obligations,
- risk and decision,
- clickable exact source spans,
- raw versus repaired result,
- net cost and end-to-end latency.

Golden flow: request 85%, fail, restore exact span, settle near 72 to 75%, match full answer.

**Exit:** deterministic local run plus deployed path.

**Commit:** `feat: certificate failure and repair demo`

## Phase 10: README, slides, and submission freeze

**2 Aug, 13:00 to 16:30**

- Freeze results and configs.
- Build 6 to 7 slides.
- Record backup video.
- Deploy, smoke-test, add collaborator, verify public links.
- Tag final commit and stop changes well before 18:00.

**Absolute rule:** no code changes after the official deadline.

## 6. Technical implementation plan

### 6.1 Core schemas

```python
class SourceSpan(BaseModel):
    source_id: str
    kind: str
    start: int | None = None
    end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    json_path: str | None = None

class Obligation(BaseModel):
    id: str
    class_name: str
    value: str
    relation: dict | None = None
    source_spans: list[SourceSpan]
    hard: bool = True

class CertificateCheck(BaseModel):
    obligation_id: str
    check_type: str
    passed: bool
    evidence: dict

class PreservationCertificate(BaseModel):
    version: str
    source_hash: str
    query_hash: str
    compressed_hash: str
    tokenizer: str
    tokens_before: int
    tokens_after: int
    checks: list[CertificateCheck]
    source_map_coverage: float
    predicted_answer_change: float
    decision: str
    restored_spans: list[SourceSpan]

class CompressionResult(BaseModel):
    raw_context: str
    final_context: str
    certificate: PreservationCertificate
    raw_metrics: dict
    final_metrics: dict
```

### 6.2 Obligation extraction

Implement overlapping extractors:

- regex and parsers for exact values,
- dependency patterns for negation/quantifiers/conditions,
- JSON and log structure parsers,
- Tree-sitter code facts,
- NER/coreference only as supporting signals.

Certificate coverage is measured against discovered obligations; fixture recall is measured against labeled `ContextProofBench` obligations.

### 6.3 Selector

```text
score = query_relevance
      + uniqueness
      + bridge_centrality
      + protected_value
      + anomaly_value
      + type_specific_value
      - redundancy
      - token_cost
      - deletion_risk
```

Seed hard obligations, preserve required connecting edges, then greedily add best marginal gain per token.

### 6.4 Document/dialogue compiler

- Preserve role boundaries.
- Deduplicate semantically equivalent units.
- Preserve latest corrections and commitments.
- Keep coherent extractive spans rather than malformed token fragments.

### 6.5 JSON/log compiler

- Parse first.
- Compare compact JSON with TOON-style representation.
- Store repeated schema once.
- Preserve counts, anomalies, extrema, errors, null changes, query matches, trace IDs, and event neighbours.
- Emit JSON paths for every retained structured fact.

### 6.6 Python compiler

- Tree-sitter parse.
- Keep imports, public signatures, types, constants, query-relevant bodies, branch guards, exception paths, and dependencies.
- Validate parsability.
- Restore broader scope on dynamic or unresolved calls.

### 6.7 Risk calibration

Features:

- failed/near-failed obligation checks,
- certificate coverage,
- missing graph edges,
- parser uncertainty,
- compression ratio,
- content type,
- query relevance margin,
- number of restored spans.

Fit logistic regression first. Use isotonic regression only if validation size is adequate. If calibration is statistically meaningless, label the score `uncalibrated` rather than disguising a heuristic.

## 7. Verification plan

### 7.1 Independent certificate verifier

The verifier receives original context, query, compressed context, source map, and certificate. It recomputes:

- source/query/compressed hashes,
- exact identifier and value checks,
- value-unit-owner relations,
- negation/quantifier/permission/condition/exception patterns,
- code AST/dependency checks,
- JSON paths, row counts, and anomalies,
- log trace/event-chain checks,
- source-map precision and coverage.

It must not import compressor-internal “passed” flags as truth.

### 7.2 Semantic checks

- Evidence-path connectivity.
- Contradiction/entailment only for checks not decidable structurally.
- Selective differential probes on high-risk or benchmark cases.

### 7.3 Recovery policy

Restore the omitted span maximizing:

```text
expected_risk_reduction / token_cost
```

Priority:

1. Failed hard obligation.
2. Broken relation or reasoning path.
3. Structural invalidity.
4. High calibrated answer-change risk.
5. Missing local context around a retained fragment.

Stop at `emit`, `expand_budget`, or `full_fallback`. Record every step in the certificate.

## 8. Benchmark implementation plan

### 8.1 Dataset adapter

```python
class BenchmarkExample(BaseModel):
    id: str
    context: str
    query: str
    reference: str | list[str]
    task_type: str
    content_type: str
    gold_obligations: list[Obligation] = []
    metadata: dict = {}
```

### 8.2 Minimum benchmark mix

- `ContextProofBench`: at least 30 deterministic cases.
- RULER: retrieval/aggregation slice.
- LongBench v2 or HELMET: small realistic slice.
- Structured JSON/log custom fixtures.
- Python dependency fixtures or RepoBench subset.

### 8.3 Scorers

- Exact Match and token F1.
- Task-specific retrieval/aggregation accuracy.
- Code parse, exact behavior, or completion score.
- Protected-fact recall.
- Critical corruption rate.
- Certificate coverage and validity.
- Source-map precision/recall.
- Reasoning-path retention.
- Brier score and ECE.
- Coverage/selective accuracy.
- Net cost and end-to-end latency.

### 8.4 Required columns

```text
dataset, example_id, method, content_type, reduction_target,
original_tokens, compressed_tokens, actual_reduction,
raw_score, certified_score, final_score,
raw_retention, certified_retention, final_retention,
certificate_coverage, certificate_validity, critical_corruption_rate,
source_precision, source_recall, predicted_risk, accepted,
restored_tokens, fallback, compressor_ms, verifier_ms, target_ms,
end_to_end_ms, input_cost, output_cost, fallback_cost, net_savings,
status, error
```

### 8.5 Result tables

Produce:

1. matched-budget method table,
2. per-format table,
3. per-protected-class table,
4. raw/certified/end-to-end table,
5. retention-reduction curve,
6. risk-coverage curve,
7. ablation table.

No final cell may contain placeholder ellipses.

## 9. Test plan

### 9.1 Unit tests

- Canonical certificate serialization and hashes.
- Independent verifier catches modified source, compressed text, or certificate.
- Exact source offsets survive normalization.
- Value-unit-owner relation remains intact.
- Role boundaries never merge.
- JSON paths and row counts are correct.
- Python output parses.
- Selector includes mandatory obligations.
- Restoration is monotonic and source-exact.
- Query change invalidates certificate.
- Short prompts bypass compression.

### 9.2 Adversarial tests

- “The service did not fail” among repeated failure statements.
- 15 ms versus 150 ms attached to different services.
- “All regions except ap-south-1”.
- An allowed action versus a prohibited action.
- Earlier fact superseded by a later correction.
- One anomalous JSON row among thousands.
- One rare log trace causing downstream failure.
- Two same-named functions in different modules.
- Query-relevant branch guard removed by code skeleton.
- Prompt injection sentence inside source data.

### 9.3 Integration tests

- Compress, verify, restore, compare, retrieve.
- Benchmark from a clean environment.
- Full, raw, certified, and final artifacts saved.
- UI against deployed API.
- Offline local fallback.

### 9.4 Final smoke test

```bash
pytest -q
python -m tracefold.benchmark --config configs/final.yaml
python -m tracefold.certificates.verify reports/golden/certificate.json
python -m tracefold.smoke --deployed-url "$URL"
```

## 10. Observability and reproducibility

Every run records:

- Git commit, config hash, data-split hash, UTC/IST timestamp.
- Tokenizer and version.
- Analyzer, verifier, calibrator, compressor, and target-model identifiers.
- Hardware and random seed.
- Source, query, raw-compressed, and final-compressed hashes.
- Certificate version and independent verification result.
- Per-stage latency and token/cost accounting.
- Predicted risk, acceptance threshold, decision, restored spans, and fallback.
- Raw, certified, and final task scores.

Save JSONL, aggregate CSV, Markdown report, and frozen figures.

## 11. Deployment plan

### 11.1 Preferred path

- Dockerized FastAPI backend.
- Streamlit or Gradio front end.
- One public deployment platform.
- Local model or cached small models bundled where platform limits allow.

### 11.2 Fallback path

- Single-process Streamlit app with compressor and local inference.
- Hosted API optional.
- Static benchmark report available even if live inference is slow.

### 11.3 Failure hardening

- Input length cap with clear message.
- Model load progress.
- Timeouts.
- Retry only idempotent calls.
- Cached golden examples.
- Health endpoint.
- No secret keys in repository or client code.

---

## 12. Demo rehearsal script

### 0:00 to 0:20, hook

“This packet is 18,000 tokens. One exception, one anomalous row, and one branch guard decide the answer.”

### 0:20 to 1:00, aggressive attempt

- Request 85% compression.
- Show certificate failure on the exception or code dependency.
- Open the exact original source span.

### 1:00 to 1:40, repair

- TraceFold restores only the required span.
- Final reduction settles near 72 to 75%.
- Certificate changes from failed to verified.

### 1:40 to 2:30, answer comparison

- Show full, LLMLingua-2/Headroom, and TraceFold answers.
- Show source evidence, retention, net cost, and end-to-end latency.

### 2:30 to 3:15, benchmark proof

- Matched-budget table.
- Raw versus certified versus end-to-end.
- Risk-coverage and retention-reduction curves.

### 3:15 to 4:00, product

- OpenAI-compatible API.
- Documents, JSON/logs, and Python.
- Private deployment.

### 4:00 to 5:00, buffer

Keep the deterministic core under four minutes.

## 13. Pitch construction plan

| Slide | Required evidence |
|---|---|
| 1 | Official target and frozen headline result |
| 2 | Headroom/LLMLingua competitive landscape and missing assurance gap |
| 3 | Typed IR, three compilers, CPRGC, certificate, risk, restoration |
| 4 | Certificate screenshot and 85% failure/repair moment |
| 5 | Matched-budget table, Pareto curve, risk-coverage, ablations |
| 6 | API, UI, net economics, deployment |
| 7 | Research contribution, ContextProofBench, closing claim |

Every number must be generated by a committed script and traceable to a frozen report.

## 14. Risk register

| Risk | Probability | Impact | Mitigation |
|---|---:|---:|---|
| Protected extractor misses the decisive obligation | High | Critical | Overlapping detectors; labeled ContextProofBench recall; report certificate coverage separately |
| Certificate validates syntax, not answerability | Medium | Critical | Relation graph and selective differential probes |
| 95% retention missed at >70% reduction | High | Critical | Adaptive restoration, certified coverage, honest fallback |
| Calibration set too small | High | High | Use simple logistic model; label heuristic risk as uncalibrated if necessary |
| Verification kills speedup | Medium | High | Deterministic checks first; risk-gate expensive probes |
| Headroom cannot be reproduced | Medium | Medium | Time-box install; use source-backed qualitative comparison, no fake numbers |
| Three compilers spread effort too thin | High | High | Keep each minimal and certificate-centered; cut P1 features first |
| Python static analysis misses dynamic behavior | High | High | Raise risk and restore broader scope |
| Structured sampling drops rare row | Medium | Critical | Preserve anomalies, extrema, errors, counts, and query matches |
| Fallback hides weak raw compressor | Medium | Critical | Always report raw/certified/end-to-end separately |
| Output token growth erases savings | Medium | High | Include output tokens in net economics |
| Demo or API outage | Medium | High | Local deterministic fallback and backup video |
| Post-deadline commit | Low | Critical | Submit early, tag, and freeze |

## 15. Go or no-go checkpoints

### Checkpoint A, 1 Aug 15:15

**Go:** obligations and exact source maps work on 20 fixtures.  
**No-go:** cut advanced NLP and use deterministic patterns; do not cut the certificate contract.

### Checkpoint B, 1 Aug 21:00

**Go:** all three minimal compilers emit source-mapped artifacts and corrupted output fails verification.  
**No-go:** simplify graph scoring, but retain independent verification and three content paths.

### Checkpoint C, 2 Aug 03:30

**Go:** recovery, target comparison, and at least four baselines run.  
**No-go:** freeze features and prioritize reproducible benchmark evidence.

### Checkpoint D, 2 Aug 10:30

**Go:** credible raw/certified/end-to-end table plus risk-coverage curve exists.  
**No-go:** narrow claims and supported formats; do not hide failures.

### Checkpoint E, 2 Aug 15:30

**Go:** deployed app, slides, public links, and backup video complete.  
**No-go:** stop feature work and execute submission checklist.

## 16. Submission checklist

### Project

- [ ] Public deployed URL works.
- [ ] Repository is accessible.
- [ ] Required collaborator is added.
- [ ] README contains setup and results.
- [ ] Final commit is tagged.
- [ ] No secrets are committed.
- [ ] Benchmark artifacts are included.

### Drive

- [ ] Repository link included.
- [ ] 6 to 7 slide presentation uploaded.
- [ ] Optional 5-minute video uploaded.
- [ ] Anyone with link can view.

### Form

- [ ] Team name.
- [ ] Team leader name.
- [ ] Team members.
- [ ] Selected track: Gen AI.
- [ ] Problem statement: PS 2, Ultra-Low Resource LLM Context Compression Engine.
- [ ] Deployed URL.
- [ ] Drive link.
- [ ] Submitted well before 6:00 PM IST.

### Freeze

- [ ] CI is green.
- [ ] Deployment matches final commit.
- [ ] Final smoke test saved.
- [ ] No changes after deadline.

---

## 17. Definition of done

TraceFold is done for Round 2 when:

1. A judge can open the deployed app without credentials.
2. A heterogeneous context can be compiled in one action.
3. The UI shows a recomputable certificate and exact source map.
4. A deliberately unsafe request is caught and repaired or rejected.
5. Full, raw-compressed, certified, and final outputs are compared fairly.
6. The four official evaluation dimensions are reported.
7. LLMLingua-2 and Headroom are addressed credibly.
8. Risk calibration and risk-coverage are visible or explicitly labeled uncalibrated.
9. Protected ledger, certificate, and fallback have positive ablation evidence.
10. Net economics include verifier, output, and fallback costs.
11. Repository, deployment, slides, and benchmark artifacts are accessible.
12. Submission is complete before the deadline.

## 18. First commands to run

```bash
mkdir tracefold && cd tracefold
git init
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic typer numpy pandas scipy scikit-learn \
  sentence-transformers networkx rapidfuzz transformers torch pytest \
  spacy tree-sitter orjson jsonschema tiktoken
mkdir -p src/tracefold/{normalize,analyzers,ir,obligations,graph,allocators,compilers,certificates,calibration,restore,source_store,adapters,metrics,schemas}
mkdir -p apps/{api,demo} benchmarks/{contextproof,adapters,baselines} configs tests reports docs
```

Implement in this order:

```text
schemas -> canonical hashes -> source map -> obligation extractors
-> three minimal compilers -> graph/selector -> certificate generator
-> independent verifier -> risk calibration -> restoration/fallback
-> target adapter -> benchmark -> demo
```

## 19. Final instruction to the team

Do not build a prettier Headroom clone or an LLMLingua wrapper. The project wins only when the proof is tangible: a certificate fails for the right reason, the exact missing span is restored, the risk estimate is honest, and the benchmark shows the trade-off without camouflage. Build the assurance primitive first. Everything else is scaffolding.
