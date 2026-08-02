# Phase 9 Claim Freeze

Evidence gate: pass

## Frozen claims

- On ContextProofBench v1 with gemini-3.1-flash-lite, TraceFold retained 45/46 answers that full context answered correctly.
- Four supported compressible fixture classes exceeded 70% configured cl100k_base context reduction.
- Python correctly returned incompressible at the protected mandatory floor.

## Compression accounting

- Mean reduction among emitted compressed contexts: 0.714093
- Fallback-adjusted aggregate reduction: 0.571274

## Prohibited claims

- Universal 95% accuracy.
- All workloads or all five source kinds exceed 70% reduction.
- Semantic equivalence is proven.
- External benchmark superiority without external benchmark evidence.

## Future triage

- `cpb-json-05`: full context correct, CPRGC wrong. Class: missing compact evidence.
  `schema_version=v2.7.4` exists in source but not compact context despite valid structural
  verification. Future work: test query-critical JSON metadata preservation without changing
  ContextProofBench v1.
- `cpb-dialogue-05`: both wrong. Class: benchmark ambiguity. Question asks who owns the
  corrected timeout, source says “use gateway-api ... for the ... timeout owner,” but accepted
  answer is `owner`. Future work: review answer-key wording in a new benchmark version.
- `cpb-document-09`: both wrong. Class: scorer limitation. Both methods returned `rollback` for
  “What begins...”; accepted answer is `rollback begins`. Future work: version a semantic
  short-answer scorer.
- `cpb-python-02`: both wrong, incompressible. Class: scorer limitation. Both methods returned
  `owner_approval`; accepted answer requires `if not owner_approval`. Future work: version a
  code-condition scorer.
- `cpb-python-09`: both wrong, incompressible. Class: model reasoning failure. Required symbol
  is present in full and fallback contexts. Future work: evaluate stable target models without
  changing current evidence.
- No full-wrong/CPRGC-correct cases, fallbacks, missing provider usage, or infrastructure
  failures occurred. Ten Python items were explicitly incompressible at the mandatory floor.
