# Phase 9 Contract: Gemini Live Paired Evidence and Claim Freeze

## Status and objective

Phase 9 runs the frozen ContextProofBench v1 paired matrix against Google Gemini,
triages disagreements without benchmark mutation, and freezes only claims supported by
the resulting evidence. Phase 8 CI run `30747775653` completed successfully. Phase 8
prepared 50 items and 100 paired `full_context`/`cprgc_target` requests, but downstream
accuracy remains unmeasured at phase entry.

CPRGC, Phase 6 fixtures, benchmark questions, answer keys, prompts, scoring rules,
tokenizer configuration, and the separate `parallel/ui-golden-demo` branch are frozen.

## Provider and model

Provider endpoint class is Google Gemini through the official OpenAI-compatible chat
endpoint at `generativelanguage.googleapis.com`. The originally preferred
`gemini-2.5-flash` and catalog-listed `gemini-2.5-flash-lite` returned HTTP 404 because
they are unavailable to new users. The frozen replacement is stable
`gemini-3.1-flash-lite`, the next cheapest active stable text model in official pricing.
Deprecated `gemini-2.0-flash-lite` shut down June 1, 2026 and is not eligible. Preview
models and silent model substitution are forbidden. Returned
model identity must remain consistent after the first benchmark response.

## Credential handling

`TRACEFOLD_API_KEY` exists only in the parent process environment. It is never entered in
chat, shell command text, source, repository files, artifacts, hashes, logs, CI, issues,
or pull requests. It is sent only as the authorization credential to the official Gemini
endpoint. Commands may report only `set`, `missing`, `unset`, or `still-set`.

Provider errors are sanitized before becoming typed responses. Before evidence commit,
the key is unset and repository/artifact scans report filenames only. Any complete key in
output, logs, diffs, or artifacts invalidates the run and requires immediate revocation.

## Provider preflight

Before any benchmark item, one uncommitted synthetic request asks for exactly `READY`
with temperature `0`, maximum output tokens `16`, and the frozen model. Preflight must
confirm HTTP success, non-empty answer, stable model identity, and parsed or explicitly
unavailable usage. Authentication, permission, malformed-response, unsupported-field,
or model-access failures stop benchmark inference.

Unsupported request fields are never silently removed. A provider capability change must
be typed, documented, tested, committed, and followed by a fresh preflight.

Gemini preflight returned `Invalid JSON payload received. Unknown name "seed": Cannot
find field.` The typed `TRACEFOLD_TARGET_SUPPORTS_SEED=0` capability therefore omits seed
for every method in Gemini runs. Other providers retain the default seed-supported
behavior. Manifests record the capability and a null random seed when seed is omitted.

## Deterministic pacing and retries

Live requests use `TRACEFOLD_INTER_REQUEST_DELAY_SECONDS=7`. Delay occurs between live
requests, never before the first. Replay and disabled modes do not sleep. Delay is fixed,
has no jitter, and is recorded in the run manifest.

Transient HTTP 408, 409, 425, 429, and 5xx responses receive at most two retries. A valid
numeric `Retry-After` value is honored within a cumulative provider-wait cap of 120
seconds per request; otherwise deterministic exponential waits are used. Authentication,
permission, validation, and malformed responses are not retried. Quota failures remain
infrastructure failures and never become semantic wrong answers.

## Tokenizer and compression accounting

All Phase 9 preparation uses `tiktoken/cl100k_base`. Fixture-byte metrics remain
regression-only. Configured context reduction is context-only and remains distinct from
provider request input reduction, which pairs provider-reported input usage for the same
item and includes prompt wrapper, question, answer format, and context.

Inherited prepared reductions are document `74.8747%`, dialogue `70.2797%`, JSON
`70.1901%`, logs `70.2927%`, and Python `0.0000%`. Python is honestly incompressible at
its protected 70% mandatory budget. Fallback-adjusted aggregate configured reduction is
`57.1274%`. Live artifacts recalculate these values rather than copying them.

Provider input, cached input, output, reasoning, target latency, local compression,
verification, recovery, and end-to-end latency remain separate. Monetary cost is null
without an explicitly approved pricing configuration; free-tier use is not production
cost evidence.

## Immutable runs

Committed live roots are:

- `reports/runs/phase9-gemini-smoke/`
- `reports/runs/phase9-gemini-primary/`
- `reports/runs/phase9-gemini-aggressive/` only when optional execution is safe

Non-empty output directories are rejected. One directory contains responses from one
model, tokenizer identity, target settings, compiler commit, and benchmark-runner commit.
Raw provider responses and temporary preflight output are never committed.

## Smoke acceptance

Smoke uses the five frozen Phase 8 IDs, one per source kind, and exactly two methods:
`full_context` and `cprgc_target`. Ten request records must exist. Acceptance requires no
authentication/permission failure, request/model/hash mismatch, malformed response, or
secret leakage; no more than one transient infrastructure failure; structurally valid
deterministic scores; and replay reproduction for every successful response. Perfect
smoke accuracy is not required.

## Primary acceptance

Primary uses all 50 frozen ContextProofBench v1 items with `full_context` and
`cprgc_target`: 100 expected requests. All items must be represented. A quota-exhausted
or interrupted run is explicitly incomplete and cannot support retention claims. No
successful response is copied between runs or mixed across commits.

## Replay validation

Replay requires exact request, response, and replay hashes; item, method, prompt,
tokenizer, model, compiler commit, and benchmark-runner commit. Missing, duplicate,
altered, or mixed-run records are infrastructure failures. Replayed successful scores
must match live scores byte-for-byte except excluded live timestamps and latency.

## Metrics

Absolute accuracy is correct successful responses divided by successful responses for a
method. Paired retention is CPRGC correct among items where full context was successful
and correct. Reports include numerator, denominator, Wilson 95% interval, both-correct,
both-wrong, full-only-correct, CPRGC-only-correct, infrastructure failures, source-kind
breakdowns, and answer-type breakdowns.

Provider request input reduction is null when either paired provider usage count is
absent. Infrastructure failures are never silently omitted or scored as ordinary wrong
answers.

## Evidence gate and claim freeze

The downstream-retention gate requires all 50 items, live or valid replay responses, a
non-zero full-context-correct denominator, paired retention at least 95%, valid final
CPRGC verification, complete mandatory coverage, complete applicable relation coverage,
separate infrastructure failures, no fallback counted as positive compression, and
honest provider-usage availability.

Passing permits only benchmark-scoped Gemini 3.1 Flash-Lite retention counts, four
compressible fixture classes above 70% configured `cl100k_base` context reduction,
Python incompressibility at the protected floor, and measured emitted/fallback-adjusted
reductions. Failing freezes the measured lower retention and its failure classes.
Incomplete primary evidence permits no downstream-retention claim.

Universal accuracy, all-workload 70% reduction, proven semantic equivalence, and external
benchmark superiority remain prohibited.

## Triage

Every disagreement, fallback, incompressible result, missing usage record, and
infrastructure failure is classified without changing benchmark data. Allowed classes
are target formatting, scorer limitation, benchmark ambiguity, missing compact evidence,
misleading compact representation, model reasoning failure, infrastructure failure, and
unknown. Proposed fixes appear only in `claim-freeze.md` for a future phase.

## Artifact provenance and failure accounting

Each run records model, official endpoint class, tokenizer identity, fixed request delay,
compiler and runner commits, request counts, failures, timestamps, and secret-free
environment summary. Required outputs are sanitized responses, scores, JSON/CSV/Markdown
summaries, failures, manifest, artifact hashes, and `claim-freeze.md` for primary
evidence. Aggregate prose is generated from scored records.

## Explicit non-goals

No CPRGC optimization, fixture or benchmark mutation, prompt/scorer change after live
inference begins, model switching within a run, competitor benchmark, UI integration,
deployment, pricing invention, main merge, pull request, or Phase 10 work.

## Exact exit commands

```text
python3.11 -m venv .venv-phase9
.venv-phase9/bin/python -m pip install --upgrade pip
.venv-phase9/bin/python -m pip install -e ".[dev]"
.venv-phase9/bin/pytest -q
.venv-phase9/bin/ruff check src tests
.venv-phase9/bin/ruff format --check src tests
.venv-phase9/bin/mypy src tests
.venv-phase9/bin/python -m compileall -q src
.venv-phase9/bin/python -m build
.venv-phase9/bin/python -m tracefold benchmark --help
git diff --check
```

Prepare `full_context,cprgc_target` twice with `tiktoken/cl100k_base` into fresh
temporary directories and compare deterministic artifacts byte-for-byte. Benchmark item
SHA-256 must remain
`c777f22e9324617a2a70c53ec3917934a0b1de121eb1b5eb8a3706ec7345c62e`.

After live evidence, rerun tests, Ruff, mypy, compileall, build, replay, artifact-hash,
benchmark-hash, protected-file, visibility, main-tip, and UI-tip checks. Unset the key,
perform filename-only secret scans, stage explicit files only, push Phase 9, and inspect
the completed CI conclusion.
