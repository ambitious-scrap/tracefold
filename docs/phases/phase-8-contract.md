# Phase 8 Contract: Production-Token-Safe Paired Evidence Run

## Status and objective

Phase 8 is a strict, benchmark-only phase. It repairs benchmark token and
coverage accounting, freezes a production-token-safe runner, and then runs the
smallest paired evidence matrix permitted by available live credentials or a
validated replay. It does not approve earlier phases.

Fixture-byte metrics are regression-only. Python remains structurally
incompressible at the 70% `tiktoken/cl100k_base` budget. Downstream accuracy is
unmeasured at phase entry. CPRGC, fixtures, benchmark questions, answer keys,
prompts, scoring rules, and method implementations are frozen. UI work remains
on the separate `parallel/ui-golden-demo` branch.

## Explicit benchmark tokenizer

Every preparation call requires one resolved tokenizer. CLI callers provide
`--tokenizer-backend` and `--tokenizer-encoding`, with
`TRACEFOLD_TOKENIZER_BACKEND` and `TRACEFOLD_TOKENIZER_ENCODING` as explicit
fallbacks. One run uses one identity for original counts, CPRGC, Phase 3,
truncation, lexical selection, matched budgets, manifests, and summaries.

Phase 8 evidence uses `tiktoken/cl100k_base`. Fixture-byte preparation is
allowed only as `fixture-only/utf8-byte` and is labelled `fixture_bytes`; it is
never provider or production-token accounting. Provider usage remains
authoritative for live request accounting.

## Prepared provenance

Each prepared context records tokenizer identity, metric source, original and
emitted configured-tokenizer counts, matched configured-tokenizer budget,
configured context reduction, compiler commit, and benchmark-runner commit.
Manifests record the same tokenizer and code provenance.

Metric sources are `fixture_bytes`, `configured_tokenizer`, and
`provider_usage`. These labels are never interchangeable.

## Direct preservation coverage

Hard-obligation coverage is:

`verified_mandatory / mandatory_obligations`

Relation coverage is:

`verified_relations / discovered_relations`

A zero denominator produces `ratio=null` and `status=not_applicable`. Prepared
records also carry mandatory and verified-mandatory counts, discovered and
verified relation counts, relation-class diversity, exact relation count, and
inferred relation count. Incomplete applicable coverage cannot pass a claim
gate.

## Matched budgets and provider usage

CPRGC target mode establishes the configured-tokenizer context budget for an
item. Every lossy baseline receives that exact budget measured with the same
tokenizer, including markers. Full context remains uncompressed.

`configured_context_reduction` measures context only with the configured
tokenizer. `provider_request_input_reduction` pairs successful provider input
usage for the same item under `full_context` and the compressed method. It
therefore includes system prompt, question, format instruction, and context.
It is null when either usage value is absent.

Input, cached input, output, reasoning, target latency, local compression,
verification, recovery, and end-to-end latency remain separate fields. Pricing
is null unless a user-supplied pricing configuration is present.

## Immutable runs and filtering

Every command accepts `--output-dir`. A non-empty run directory is rejected;
one run never overwrites another. Committed run roots are:

- `reports/runs/phase8-smoke/`
- `reports/runs/phase8-primary/`
- `reports/runs/phase8-aggressive/`

Item filtering uses a committed `--item-ids-file`. The smoke file contains
exactly five items, one per source kind. The optional aggressive file contains
exactly ten items, two per source kind. Unknown, duplicate, or mixed-run item
IDs fail before requests.

Each completed run contains benchmark items, method definitions, prepared
contexts, sanitized responses when available, scored results, JSON and CSV
summaries, generated Markdown and failure reports, manifest, and artifact
hashes. Raw provider responses never enter committed directories.

## Replay validation

Replay requires exact request hash, model, item, method, prompt hash, tokenizer
identity, compiler commit, and benchmark-runner commit. Duplicate, missing, or
mixed-run records are infrastructure failures, not wrong answers. Sanitized
records never contain keys, authorization headers, cookies, secret environment
values, or raw headers.

## Frozen execution sets

Smoke: five frozen items with `full_context` and `cprgc_target`; ten expected
requests.

Primary: all 50 ContextProofBench v1 items with `full_context` and
`cprgc_target`; 100 expected requests.

Optional aggressive: ten frozen items with `full_context` and
`cprgc_aggressive`; 20 expected requests, only after primary completion.

Live inference requires `--confirm-live` or
`TRACEFOLD_ALLOW_LIVE_BENCHMARK=1`. No live command is the default.

## Evidence and claim gate

Artifacts report absolute full-context and CPRGC accuracy, paired retention on
the full-context-correct subset, Wilson 95% intervals, paired disagreement
counts, per-source and per-answer-type results, configured context reductions,
provider request reductions, token usage, latency, cost or null reason, and all
infrastructure failures.

The gate passes only with live or hash-validated replay responses for all 50
items, a non-zero full-context denominator, paired retention at least 95%, mean
configured-tokenizer context reduction at least 70%, valid final CPRGC
verification, complete mandatory coverage, complete applicable relation
coverage, and no fallback counted as compression. Python's per-fixture 70%
limitation is reported separately. The gate is frozen before inference.

## Non-goals

No CPRGC optimization, fixture edits, benchmark question or answer changes,
prompt or scorer changes, UI, deployment, model training, neural compression,
LLM judging, broad baseline matrix, main merge, pull request, or Phase 9 work.

## Exit commands

```bash
python3.11 -m venv .venv-phase8
.venv-phase8/bin/python -m pip install --upgrade pip
.venv-phase8/bin/python -m pip install -e ".[dev]"
.venv-phase8/bin/pytest -q
.venv-phase8/bin/ruff check src tests
.venv-phase8/bin/ruff format --check src tests
.venv-phase8/bin/mypy src tests
.venv-phase8/bin/python -m compileall -q src
.venv-phase8/bin/python -m build
.venv-phase8/bin/python -m tracefold benchmark --help
.venv-phase8/bin/tracefold benchmark prepare --tokenizer-backend tiktoken --tokenizer-encoding cl100k_base --output-dir /tmp/phase8-prepare-a
.venv-phase8/bin/tracefold benchmark prepare --tokenizer-backend tiktoken --tokenizer-encoding cl100k_base --output-dir /tmp/phase8-prepare-b
cmp -s /tmp/phase8-prepare-a/artifact-hashes.json /tmp/phase8-prepare-b/artifact-hashes.json
git diff --check
```

Before commit, verify CPRGC, Phase 6 fixtures, Phase 7 questions, answers,
prompts, scorers, protected documents, local-only files, and
`parallel/ui-golden-demo` remain unchanged.
