# TraceFold

**Proof-carrying context compression for production AI systems.**

TraceFold turns long source context into compact, source-mapped evidence that AI systems can use efficiently. Every compression result carries deterministic certificates, structural verification, recovery history, and traceable links to the original source.

## Why TraceFold

- **Verifiable compression** — independently checks protected facts, obligations, relations, and source-map coverage.
- **Traceable evidence** — connects compact output back to source spans with cryptographic artifact hashes.
- **Deterministic recovery** — repairs verification failures through recorded, reproducible recovery actions.
- **Production-ready API** — compress documents, dialogue, JSON, logs, and Python through one typed endpoint.
- **Interactive proof workbench** — explore compressed context, certificates, verification, recovery, lineage, and benchmark evidence.
- **Local-first operation** — ordinary compression and the complete product demo require no provider API key.

## Measured results

On **ContextProofBench v1** with **Gemini 3.1 Flash-Lite**, TraceFold retained **45 of 46 answers** the full context answered correctly: **97.8261% paired retention** with a **Wilson 95% interval of 88.6647%–99.6152%**.

- **100 successful live paired requests**
- **71.4093% mean reduction** among emitted compressed contexts
- **54.563862% provider-reported request-input reduction**
- **Four compressible source classes exceeded 70% configured `cl100k_base` context reduction**

Frozen evidence and reproducible artifacts:

- [`reports/runs/phase9-gemini-primary/`](reports/runs/phase9-gemini-primary/)
- [`reports/runs/phase9-gemini-smoke/`](reports/runs/phase9-gemini-smoke/)

## Run the proof workbench

Start the backend:

```bash
python -m pip install -e ".[dev]"
python -m uvicorn tracefold.api:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```bash
cd web
npm ci
VITE_TRACEFOLD_API_MODE=backend npm run dev
```

Open `http://127.0.0.1:5173`.

## Compression API

```bash
curl -s http://127.0.0.1:8000/v1/compress \
  -H 'content-type: application/json' \
  -d '{"source_text":"The timeout is 5000 ms for gateway-api.","source_kind":"document","mode":"target","tokenizer_backend":"tiktoken","tokenizer_encoding":"cl100k_base","maximum_recovery_attempts":3}'
```

Explore frontend capabilities in [`web/README.md`](web/README.md) and API mapping in [`web/BACKEND_INTEGRATION.md`](web/BACKEND_INTEGRATION.md).
