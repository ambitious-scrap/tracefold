# Backend integration boundary

The UI owns one adapter: `src/api/tracefoldClient.ts`. Views consume the typed
contracts in `src/contracts/tracefold.ts` and should not issue fetch calls.
Phase 10 integration should primarily change the adapter mapping and the
contract validators.

## Request

`POST /v1/compress`

```json
{
  "sourceKind": "document",
  "sourceText": "...",
  "query": "optional question or selection hint",
  "mode": "target",
  "exactBudget": null,
  "tokenizerIdentity": "configured tokenizer identity",
  "maximumRecoveryAttempts": 3,
  "fixtureId": "verified-target"
}
```

The adapter sends JSON with `content-type: application/json`. No target-model
request is made by the UI; `/v1/compress` is the compressor/verifier boundary.

## Response mapping

The current adapter accepts a complete `DemoScenario` under `demo_scenario`,
`scenario`, or the response root. This is deliberately a narrow temporary
mapping. The response should eventually expose these typed groups:

- `result`: final status/action, original/raw/final sizes, requested/raw/final
  reduction metrics, certificate status, verification status, and warnings.
- `certificate`: source, normalized-source, compressed-artifact, certificate,
  and query hashes; tokenizer identity; component versions; obligation and
  relation coverage; rule observations; failed invariants; and trust-boundary
  note.
- `recovery`: append-only stages with artifact hashes, effective budgets,
  actions, metric source, failed invariants, restored spans, verification, and
  recovery-history hashes.
- `source`, `compactContext`, `compactFragments`, `sourceSpans`, and `sourceMap`:
  source IDs, coordinates, mapping cardinality, output kind, exactness,
  obligation IDs, relation IDs, and source labels.

The static adapter validates only the envelope today. Phase 10 should replace
that with schema validation before rendering backend data.

## Metric-source rules

Every reduction metric must retain `source`:

- `fixture_bytes` → **Structural byte reduction**. Never call it token
  reduction.
- `configured_tokenizer` → **Token reduction · `<encoding identity>`**.
- `provider_usage` → **Provider-reported input-token reduction · `<model>`**.

Do not infer one source from another. Keep raw and final reductions separate.
Null downstream retention remains `Unmeasured` or `Prepared only`; it is never
converted to zero.

## Certificate and verification fields

The UI distinguishes certificate candidate status from independent verification
status. A valid structural certificate is displayed as machine-verifiable
structural preservation evidence, not as cryptographic semantic equivalence or
downstream answer retention.

Zero discovered relations must remain `Not applicable`, not `100%`.

## Recovery fields

The UI expects repository-backed or runtime-recorded stages only. A fallback
must keep the failed invariant visible and report zero final savings. A stage
with no recorded hash, budget, count, or restored span renders `Not recorded`.

## Error states

Backend HTTP failures and network failures are sanitized by the adapter. When
committed static data is available, backend mode returns the selected static
scenario with `usedStaticFallback: true` and a recoverable error. Secrets,
provider responses, and remote endpoint details must not be forwarded to JSX.

## Phase 7R handoff

Expected changes after Phase 7R are limited to field names and richer per-rule,
source-map, and recovery observations. Do not make component code depend on a
Phase 7 API placeholder. Update the adapter mapping and contract guard first,
then add fixture-backed adapter tests before enabling backend mode in a demo.
