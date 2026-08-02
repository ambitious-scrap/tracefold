# TraceFold Phase 7 Contract — Target Integration and Paired Benchmark Evidence

Status: frozen implementation contract for `phase/7-benchmarks-target-integration`.

## Objective

Measure downstream answer retention, matched-budget baseline quality, input-token
reduction, input cost, and complete end-to-end latency for CPRGC. Phase 7 adds a
small provider-neutral target adapter and a reproducible offline-first benchmark
harness. It does not turn structural verification into a claim of semantic
answer equivalence.

The benchmark's primary answer-retention metric is paired retention on items for
which `full_context` is correct. Results are valid only when target responses are
live or come from hash-checked sanitized replay records. Prepared-only artifacts
prove harness readiness and structural compression only.

## Inherited issues recorded for final audit

- Phases 1 through 6 remain unreviewed.
- Phase 6 compression results are synthetic structural results; no downstream
  answer-retention evidence existed before this phase.
- Phase 5 calibration uses three synthetic validation records and is not
  real-world calibration.
- Phase 6 has no dictionary-encoding candidate.
- Aggressive Phase 6 logs and Python exceed the 80% mandatory budget.
- Owner/unit tampering has no separate parameterized Phase 6 test.
- Repository-wide Markdown Ruff discrepancy remains.
- `mypy tracefold` versus the `src/` layout mismatch remains.
- Starlette/httpx deprecation warning remains.

## Allowed files and dependencies

New code is limited to `src/tracefold/benchmark.py`,
`src/tracefold/target.py`, `src/tracefold/phase7_fixtures.py`,
`src/tracefold/phase7_report.py`, `src/tracefold/schemas/phase7.py`, tests,
committed sanitized artifacts under `reports/final/`, and this contract.
Existing compressor, CPRGC, certificate, verifier, recovery, hashing, logging,
source-map, and tokenizer interfaces remain authoritative. No new dependency is
required. HTTPX is reused for live requests and mock transports.

## Target adapter protocol

`TargetAdapter` accepts a typed `TargetRequest` and returns a typed
`TargetResponse`. It supports `live`, `replay`, and `disabled` modes.

Configuration comes from explicit config or these environment variables:

- `TRACEFOLD_API_BASE_URL`
- `TRACEFOLD_API_KEY`
- `TRACEFOLD_TARGET_MODEL`
- `TRACEFOLD_API_MODE`
- `TRACEFOLD_REQUEST_TIMEOUT_SECONDS`

No model or endpoint is hard-coded. `live` requires explicit live permission;
`full-live` also requires `--confirm-live` or
`TRACEFOLD_ALLOW_LIVE_BENCHMARK=1`. Missing credentials never fabricate an
answer. `disabled` returns a typed unavailable result. `replay` uses only
sanitized, hash-checked records and never performs network I/O.

The adapter sends an OpenAI-compatible chat request with identical system
prompt, user prompt, temperature `0.0`, maximum output tokens, and optional
seed for full and compressed methods. It accepts a standard `choices[0].message`
response and `usage` fields, while preserving sanitized provider errors. It
retries transient 408, 409, 425, 429, and 5xx failures at most twice with fixed
backoff `0.25s`, `0.5s`; authentication, validation, malformed-response, and
timeout failures are not retried except timeout is recorded as infrastructure
failure. Secrets, authorization headers, cookies, and full provider headers are
never persisted or logged.

## Typed target and usage records

`TargetRequest` fields: request ID, benchmark item ID, method ID, model ID,
system prompt, user prompt, context, temperature, maximum output tokens, seed,
timeout, metadata, request hash.

`TargetResponse` fields: request ID, safe provider request ID, returned model,
answer, finish reason, input/output tokens, cached input tokens, reasoning
tokens, latency, time-to-first-token, HTTP status, retry count, sanitized error
code/message, raw-response hash, replay-record hash, and status.

`UsageAccounting` distinguishes provider-reported usage, configured production
tokenizer usage, and fixture-tokenizer usage. Provider usage is final truth for
live cost/accounting. Fixture-token counts are labeled local and cannot be
reported as provider savings. Character counts are never token counts.

## Benchmark item and method schemas

`BenchmarkItem` contains item ID, source kind, context, question, answer type,
accepted answers, exact numeric value, required units and identifiers,
supporting source spans, protected obligation IDs, required relation IDs,
difficulty, task family, query hash, and notes. IDs, source spans, answer keys,
and generated contexts are deterministic.

Answer types are `exact_string`, `identifier`, `number`, `number_with_unit`,
`date`, `boolean`, `categorical`, `ordered_list`, `set`, `json_field`,
`code_symbol`, and `short_free_text`.

`ContextProofBench v1` contains 50 questions: 10 each for document, dialogue,
JSON, logs, and Python. `ControlledContextStress v1` is a separate deterministic
local suite containing needle, multi-key, ordered-event, aggregation, recency,
relation-bridge, attribution, and distractor retrieval tasks. It is not named
or reported as RULER, LongBench, or HELMET.

Runnable methods:

- `full_context`: original context.
- `head_truncation`: first matched target-token units.
- `tail_truncation`: last matched target-token units.
- `head_tail`: deterministic half split.
- `lexical_top_k`: highest deterministic lexical-overlap segments.
- `phase3_extract`: existing Phase 3 compressor at matched budget.
- `cprgc_target`: CPRGC target mode with verification/recovery.
- `cprgc_aggressive`: CPRGC aggressive mode with verification/recovery.

Every lossy method receives exactly CPRGC's final context-token budget for the
same item. All markers and metadata included in context count. Full context is
not budget-matched and remains the reference condition. If production token
encoding is unavailable, every local method uses the configured deterministic
fixture tokenizer and results are labeled local-token results.

## Prompt and decoding contract

All methods use one prompt:

```text
System: You are answering questions using only the supplied context. Return only
the requested answer. Do not explain unless the question explicitly requests an
explanation. If the answer is absent, return NOT_FOUND.

User:
CONTEXT:
<context>

QUESTION:
<question>

ANSWER FORMAT:
<answer type>
```

Method identity never appears in the prompt. Temperature is `0.0`, seed is
fixed when supported, and output cap is fixed for every method in a run.

## Scoring

Scoring is deterministic. Unicode normalization is NFC; surrounding whitespace
is removed; case folding and punctuation removal occur only for answer types
where the contract marks them harmless. Negation, symbols, identifiers, units,
and meaningful punctuation remain significant.

Implemented scorers: normalized exact match, token F1, exact numeric with unit,
canonical date, boolean, categorical, order-sensitive list, order-independent
set, JSON path/value, exact code symbol, and `NOT_FOUND`. No LLM judge is used.

For method `m`, `A_m = correct_m / N`. Paired retention is
`PR_m = (compressed correct AND full correct) / full correct`. Absolute accuracy,
full-correct denominator, compressed-only/full-only disagreements, and
per-source-kind and per-answer-type results are mandatory. Wilson 95% intervals
are used for proportions. McNemar exact testing is optional and never used to
inflate a small-sample claim.

## Compression, cost, and latency

Reduction is `1 - compressed_input_tokens / original_input_tokens`. Raw,
final-repaired, provider-reported, fallback-adjusted, mean, median, and
per-kind reductions are separate fields. Recovery or fallback can only lower
final reduction.

Pricing is supplied through `pricing-config.example.json` or explicit pricing
config. Model, currency, input/output/cache/reasoning prices, effective date,
and source note are required. Absent prices produce null monetary fields, never
invented savings. Output-token changes are reported. Local CPU is measured but
not called free compute; compressor API cost is zero for this local compressor.

Full latency is target request duration. Compressed end-to-end latency includes
extraction, compression, certificate, verification, recovery, and target request.
Speedup is `full_latency / compressed_end_to_end_latency`; below one means
slowdown. Live durations are monotonic wall time, excluded from deterministic
hashes; medians and P90 are reported when sample count permits.

## Replay and failure accounting

Sanitized replay records contain request hash, model ID, answer, usage, latency,
finish reason, sanitized error, response hash, timestamp, and safe provider
request ID. Request/response hashes are rechecked before scoring. Wrong hashes,
model mismatch, duplicates, missing responses, and malformed records are typed
infrastructure failures. Failed requests are not silently scored as wrong
answers and remain in failure ledgers and denominators documentation.

## Execution modes and request control

Commands are equivalent to:

```text
tracefold benchmark prepare
tracefold benchmark smoke-live
tracefold benchmark full-live --confirm-live
tracefold benchmark replay
tracefold benchmark report
```

Preparation never calls a target model. `smoke-live` defaults to ten items and
four methods (`full_context`, `head_tail`, `lexical_top_k`, `cprgc_target`).
`full-live` requires explicit permission and prints model, item count, method
count, and expected request count first. Item and method filters are supported.

## Result artifacts

Generated under `reports/final/`:

- `benchmark-items.jsonl`
- `benchmark-methods.json`
- `prepared-contexts.jsonl`
- `responses-sanitized.jsonl` when available and safe
- `scored-results.jsonl`
- `summary.json`
- `summary.csv`
- `benchmark.md`
- `failures.md`
- `aggressive-demo.json`
- `run-manifest.json`
- `pricing-config.example.json`

Aggregates are generated from JSONL. Manifest records git commit, dirty state,
model, endpoint class, tokenizer, benchmark/method versions, item/request
counts, timestamp, pricing hash, seed, failures, and secret-free environment
summary. Unsanitized responses belong only in ignored local storage and are not
created by preparation.

## Gate and claim policy

Primary gate requires 50 questions, five kinds, full/head-tail/lexical/Phase 3/
CPRGC methods, CPRGC final mean reduction at least 70%, paired retention at
least 95%, complete hard-obligation and required-relation coverage, CPRGC paired
retention above `head_tail`, and above or tied with `lexical_top_k` at materially
higher reduction. No kind may have paired retention below 90%. Infrastructure
failures remain separate. The gate is `unmeasured` unless live or valid replay
responses exist. Prepared structural artifacts cannot pass an answer-retention
gate.

Aggressive demo has 10–15 adversarial questions covering negation, exception,
correction, JSON anomaly, log predecessor/trace, Python guard/caller, and
quantity owner/unit. It reports raw verification, recovery action, final
reduction, final verification, and answer correctness. No raw aggressive result
is presented as final after recovery.

## Explicit non-goals

No target-model training/calls outside explicit live mode, semantic answer
equivalence claim without paired evidence, neural compression, embeddings, NLI,
LLM judges, external datasets, competitor integrations, LLMLingua/DAC unless a
separately authorized timeboxed attempt is runnable, frontend, deployment,
databases, persistent hidden source storage, provider SDKs, or Phase 8 work.

## Exact exit commands

```bash
python -m pip install -e ".[dev]"
pytest -q
ruff check src tests
ruff format --check src tests
mypy src tests
python -m compileall -q src
python -m build
python -m tracefold --help
python -c "from tracefold.api import app; print(app.title)"
python -m tracefold.phase6_report
python -m tracefold.phase7_report
git diff --check
```

Preparation and report canonical JSON are run twice and compared byte-for-byte,
excluding live timestamps and latency. Protected Phase 0–6 files remain
unchanged. Commit only explicit Phase 7 files with:

```bash
git commit -m "feat: add paired context-compression benchmarks"
git push origin phase/7-benchmarks-target-integration
```
