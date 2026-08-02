# TraceFold

TraceFold compiles long context into a smaller artifact, binds preserved facts and relations to source evidence, and independently verifies structural invariants. Unsafe compression is repaired or reported incompressible; ordinary compression makes no target-model request.

## Local demo

No API key is required.

```bash
python -m pip install -e ".[dev]"
python -m uvicorn tracefold.api:app --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
cd web
npm ci
VITE_TRACEFOLD_API_MODE=backend npm run dev
```

Open `http://127.0.0.1:5173`. Without backend mode, UI uses committed static data. If backend mode is unavailable, UI labels any substituted scenario **Demo fallback** and does not present it as a result for custom input.

## Compression API

```bash
curl -s http://127.0.0.1:8000/v1/compress \
  -H 'content-type: application/json' \
  -d '{"source_text":"The timeout is 5000 ms for gateway-api.","source_kind":"document","mode":"target","tokenizer_backend":"tiktoken","tokenizer_encoding":"cl100k_base","maximum_recovery_attempts":3}'
```

## Frozen Phase 9 evidence

On ContextProofBench v1 with `gemini-3.1-flash-lite`, TraceFold retained 45/46 answers full context answered correctly (97.8261%; Wilson 95% interval 88.6647%–99.6152%). Absolute results were 46/50 full context and 45/50 TraceFold. Mean reduction among emitted contexts was 71.4093%; fallback-adjusted aggregate reduction was 57.1274%; provider-reported request-input reduction was 54.563862%. Python was incompressible at its protected mandatory floor.

Evidence: [`reports/runs/phase9-gemini-primary/`](reports/runs/phase9-gemini-primary/) and [`reports/runs/phase9-gemini-smoke/`](reports/runs/phase9-gemini-smoke/).

These results are benchmark- and model-specific. They do not establish universal accuracy, 70% reduction for every source kind, semantic equivalence, external superiority, or monetary production cost.

Frontend details: [`web/README.md`](web/README.md). Backend mapping: [`web/BACKEND_INTEGRATION.md`](web/BACKEND_INTEGRATION.md).
