# TraceFold proof workbench

Judge-facing React/Vite UI for the TraceFold structural compression demo. It
compiles long context into a smaller source-mapped representation and makes
the certificate, verifier boundary, recovery history, and benchmark limits
visible.

The visual system uses an editorial graphite/cool-white SaaS palette with a
single cobalt product accent and separate semantic evidence colors. Inter
Tight leads display typography, Inter handles interface copy, and IBM Plex
Mono is reserved for source evidence, hashes, and compact metrics. The landing
page loads those families from Google Fonts and retains system fallbacks.

## Install and run

```bash
cd web
npm install
npm run dev
```

Routes:

- `/` — product overview and guided entry into the workbench
- `/compress` — compression request, raw/final metrics, and source-map viewer
- `/proof` — certificate identity, coverage, rules, and trust boundary
- `/recovery` — ten-stage recovery/fallback timeline
- `/benchmarks` — prepared ContextProofBench evidence and honest empty states
- `/architecture` — compiler, verifier, recovery, and target-evaluation pipeline

## Verify

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

Tests are Vitest/jsdom tests and do not require the Python backend.

## Static demo mode

Static mode is the default. It reads the committed sanitized bundle at
`public/demo-data/index.json`. Regenerate it from the repository root with:

```bash
python3.11 tools/export_ui_demo_data.py
```

The exporter is deterministic, uses committed reports and fixtures, makes no
network calls, and does not import or modify backend implementation code.
Static mode makes no live target-model requests.

The four labelled scenarios are verified target compression, aggressive
incompressible/budget expansion, Phase 5 full fallback, and a prepared-only
benchmark state. The fallback fixture is explicitly policy evidence; it is not
presented as a measured runtime event.

## Backend mode

Set Vite environment values before starting or building:

```bash
VITE_TRACEFOLD_API_MODE=backend \
VITE_TRACEFOLD_API_URL=http://localhost:8000 \
npm run dev
```

The single adapter posts to `/v1/compress`. If the backend is unavailable, the
UI returns to the committed scenario and shows a recoverable error. See
`BACKEND_INTEGRATION.md` for the field boundary.

## Claim limits

- Structural demo data is synthetic.
- Fixture-byte metrics are not production tokenizer measurements.
- Fixture-byte reduction is labelled **Structural byte reduction**, never token
  reduction.
- Downstream answer retention is currently unmeasured; no accuracy is inferred
  from structural verification.
- No live model calls occur in static mode.
- Structural verification is machine-verifiable preservation evidence, not a
  claim of cryptographic semantic equivalence.

## Integration after Phase 7R

Keep this branch isolated while Phase 7R completes. Rebase or cherry-pick the
UI commit onto `phase/10-ui-golden-demo` only after reviewing any contract
changes. Update `src/api/tracefoldClient.ts` and its adapter tests first, map
the finalized response fields, regenerate sanitized artifacts if required,
then run the full web verification commands. Do not enable live target-model
evaluation until benchmark configuration, pricing, and paired retention data
are separately recorded.
