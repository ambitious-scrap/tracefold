# TraceFold Phase 5 Contract — Structural Risk and Verified Recovery

Status: frozen implementation contract for `phase/5-risk-recovery`.

## Objective

Add deterministic structural-failure assessment and bounded recovery around the
Phase 3 compressor and Phase 4 certificate/verifier. The system may estimate
only deterministic verification/recovery failure risk. It makes no claim about
downstream answer change.

## Allowed implementation surface

```text
docs/phases/phase-5-contract.md
src/tracefold/schemas/phase5.py
src/tracefold/risk.py
src/tracefold/recovery.py
src/tracefold/phase5_report.py
src/tracefold/certificates.py       # end_to_end recovery fields only
src/tracefold/verifier.py           # end_to_end/history/risk validation only
src/tracefold/schemas/__init__.py
tests/test_phase5.py
tests/fixtures/phase5/
```

No dependency is added. Existing compression, certificate, verifier, hashing,
source-map, tokenizer, extraction, and coordinate interfaces remain the source
of truth.

## Risk models

`StructuralRiskFeatures` contains only deterministic evidence: verification
status, failed-invariant totals/by severity/by class, per-class obligation and
relation coverage, source-map coverage, discovery-state counts, warning and
omission counts, requested/achieved reduction, mandatory floor, budget margin,
tokenizer/map/hash/query/compression failure indicators, and incompressible
state.

`StructuralRiskAssessment` contains a versioned feature hash, raw structural
failure score, nullable calibrated `structural_failure_probability`, explicit
calibration status, optional model ID, sample count, threshold, action, and
reason codes. A calibrated probability means probability of deterministic
verification failure or non-`emit` recovery on the frozen synthetic outcome,
never probability of answer change.

Calibration statuses are `calibrated`, `insufficient_data`, and
`not_available`. Fewer than 30 usable records leaves probability `null` and
status `insufficient_data`. No score is presented as calibrated with fewer
than 30 records.

`CalibrationRecord` uses outcome `1` for deterministic verification failure or
required non-`emit` recovery, and `0` for independently valid `emit`. Splits
are assigned by stable example ID. `CalibrationModel` uses pure-Python
isotonic regression (pool-adjacent-violators), fixed train/validation splits,
six-decimal metrics, feature/model/data hashes, and no runtime randomness.
Metrics are Brier score, fixed-bin expected calibration error, threshold
coverage, and structural selective verification success.

## Recovery models and actions

`RecoveryRequest` carries source, request, extraction, raw result, certificate
candidate, current verification report, attempt limit, maximum final budget,
permitted reduction loss, allowed actions, and deterministic options. The
recovery call receives tokenizer registry separately. `RecoveryPlan`,
`RecoveryAttempt`, `RecoveryHistory`, and `RecoveryResult` are immutable typed
records.

Public library functions are `extract_structural_risk_features`,
`fit_isotonic_calibrator`, `assess_structural_risk`,
`coverage_at_threshold`, `selective_verification_success`,
`verify_calibration_model`, `recover_and_verify`,
`build_recovery_history`, and `verify_recovery_history`.

The only actions are `emit`, `restore_spans`, `expand_budget`, and
`full_fallback`.

- `emit`: current certificate independently verifies with no critical failure.
- `restore_spans`: a small exact failed-invariant span set is available and
  can be restored within limits.
- `expand_budget`: mandatory evidence floor or exact restoration needs a larger
  permitted controller budget.
- `full_fallback`: parser/map/tokenizer failure, unavailable evidence, exhausted
  attempts, or impossible maximum budget. Final bytes equal original bytes and
  reduction is exactly zero.

The verifier result, never the risk score alone, controls safety. Every
recovery attempt is independently re-verified before the next action or final
return.

## Restoration and budget rules

Failed-invariant source spans are validated against source ID, source hash,
source-map bounds, and UTF-8 coordinates; overlapping/adjacent ranges merge in
source order. Document/dialogue recovery restores complete sentence,
paragraph, or message-turn ranges. JSON recovery restores complete path/value
pairs or rows. Log recovery restores complete event lines and exact correlated
predecessors. Python recovery restores complete source-line/AST ranges and
requires `ast.parse` success.

Recovery first retries deterministic compilation using an evidence-supported
budget. The next budget is:

```text
min(maximum_final_token_budget,
    max(current_budget + required_restoration_tokens,
        mandatory_floor + marker_overhead + safety_margin))
```

No percentage growth or unbounded loop is allowed. Expansion requires a
strictly larger effective controller budget. Default restoration threshold is
8 source spans and default safety margin is 8 tokens; both are deterministic
options.

## Recovery history and certificate boundary

Each attempt records attempt number, parent attempt hash, action, input/output
artifact hashes, effective budget, restored source spans, verification-report
hash, result status, deterministic timestamp input, and attempt hash. Event
hashes use `tracefold:recovery-event:1` over the canonical event excluding its
hash. Ordered history uses `tracefold:recovery-history:1`; sequence starts at
zero, parents must match, and records are append-only.

Phase 5 permits existing certificate `artifact_role: end_to_end` to carry
risk, restored spans, fallback reason, and non-empty history. Phase 4
`raw`/`certified` behavior remains unchanged. The verifier recomputes risk
feature/model hashes, history events, history head/count/hash, restored span
identity, and final artifact identity. It does not execute recovery.

## Failure behavior

Typed failures cover missing evidence, stale source/map, unknown tokenizer,
invalid budgets, foreign/out-of-bounds spans, malformed restored JSON/Python,
recompression/certificate/verification errors, broken history, and attempt
exhaustion. No failed step is swallowed. Fallback retains the original raw
failure in history and reports no compression saving.

## Acceptance tests

Tests cover deterministic features, isotonic calibration, minimum sample
behavior, Brier/ECE, deterministic train/validation split, valid emit,
negation/exception/owner/correction/anomaly/log predecessor/trace/Python guard
restoration, budget expansion, maximum-budget fallback, malformed map,
unknown tokenizer, attempt exhaustion, exact full fallback, certificate
regeneration, independent re-verification after every attempt, all history and
calibration tamper fields, invalid restored structures, deterministic report
reruns, and byte-identical recovery artifacts.

## Explicit non-goals

No target-model calls, answer comparison, LLM/NLI/embedding models, learned
selectors, production tokenizers, benchmarks, persistence, databases,
background workers, distributed orchestration, frontend, TypeScript,
deployment, authentication, or Phase 6 compressor improvements.

## Inherited final-audit items

- Phase 3 fixture reductions remain far below the official 70% target.
- Repository-wide Markdown Ruff discrepancy.
- `mypy tracefold` conflicts with the repository `src/` layout.
- Existing Starlette/httpx TestClient deprecation warning.
- Phases 1 through 4 remain unreviewed.

## Exit commands

```bash
python -m pip install -e "[dev]"
pytest -q
ruff check src tests
ruff format --check src tests
mypy src tests
python -m compileall -q src
python -m build
python -m tracefold --help
python -c "from tracefold.api import app; print(app.title)"
git diff --check
python -m tracefold.phase5_report
```
Recovery implementation note: existing compressor deterministic options only
are used for recovery. `restore_span_ids` marks validated source evidence as
mandatory; `force_full` selects byte-identical full-context fallback.
Restoration compares original and repaired achieved reduction against
`maximum_permitted_reduction_loss`. Full fallback is explicit and may report
zero reduction when no repaired compressed artifact satisfies that limit.
