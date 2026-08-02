# Backend integration

Start API:

```bash
python -m uvicorn tracefold.api:app --host 127.0.0.1 --port 8000
```

Start UI:

```bash
cd web
VITE_TRACEFOLD_API_MODE=backend npm run dev
```

`web/src/api/tracefoldClient.ts` is the network boundary. It maps UI camelCase fields to frozen `PublicCompressionRequest` snake_case fields and validates `PublicCompressionResponse` before mapping it into UI state. It never sends fixture IDs, API keys, provider configuration, endpoint details, or target-model IDs.

Runtime results use submitted source text, exact `compressed_context`, tokenizer identity, separate raw/final token counts and reductions, certificate/verifier status, failed invariants, recovery summary, warnings, and source-map counts.

Public response includes source-map summary counts but not detailed span records. Runtime UI therefore says: “Source-map summary available. Detailed span mappings are not included in the public response.” It never fabricates lineage. Committed static scenarios can show detailed mappings emitted by local TraceFold library calls.

Expected HTTP failures receive sanitized UI messages. If static fallback exists, UI labels it **Demo fallback** and states it is not a result for custom source.

Frozen live evidence comes only from `reports/runs/phase9-gemini-primary/` and `reports/runs/phase9-gemini-smoke/`. Ordinary compression makes no target-model request and requires no provider key.
