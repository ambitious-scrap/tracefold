# TraceFold proof workbench

React/Vite UI for local TraceFold compression and committed Phase 9 evidence. No API key or target-model request is required.

## Run

Static mode:

```bash
npm ci
npm run dev
```

Backend mode, after starting FastAPI on port 8000:

```bash
VITE_TRACEFOLD_API_MODE=backend npm run dev
```

Vite proxies `/v1`, `/healthz`, and `/version` to `http://127.0.0.1:8000`. Static data remains at `/demo-data/index.json`. Backend failure uses a clearly labelled **Demo fallback** only when a committed scenario exists.

## Data and claims

`tools/export_ui_demo_data.py` reads frozen artifacts from:

- `reports/runs/phase9-gemini-primary/`
- `reports/runs/phase9-gemini-smoke/`

It also runs local CPRGC over committed benchmark contexts to export actual certificates, verifier reports, and source-map records. Export is deterministic and performs no network request.

UI reports 45/46 paired retention alongside 46/50 full-context and 45/50 TraceFold absolute results, Wilson uncertainty, separate compression accounting, Python incompressibility, and committed failure triage. It makes no universal accuracy or semantic-equivalence claim.

## Quality

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```
