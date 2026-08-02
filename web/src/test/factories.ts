import type {
  ArtifactSize,
  BenchmarkData,
  CertificateData,
  CompactFragment,
  DemoBundle,
  DemoScenario,
  ReductionMetric,
  RecoveryData,
  RecoveryStage,
  SourceDocument,
  SourceSpan,
} from "../contracts/tracefold";

export function makeMetric(value: number | null, source: ReductionMetric["source"] = "fixture_bytes"): ReductionMetric {
  return {
    value,
    source,
    scope: source === "provider_usage" ? "provider" : "final",
    counterIdentity: source === "fixture_bytes" ? "Fixture byte counter · v1" : "cl100k_base",
    modelIdentity: source === "provider_usage" ? "demo-model" : null,
    synthetic: true,
  };
}

function makeSize(label: ArtifactSize["label"], bytes = 18): ArtifactSize {
  return { label, bytes, tokens: null };
}

export const source: SourceDocument = {
  id: "src:test:document",
  label: "Document / test fixture",
  kind: "document",
  text: "Policy: owner approval is required.\nTimeout: 5000 ms.\nRelation: timeout belongs to gateway-api.",
  hash: "sha256:test-source",
  generatedFrom: "tests/fixtures/test.txt",
};

export const sourceSpan: SourceSpan = {
  id: "span:test:timeout",
  sourceId: source.id,
  sourceStart: 47,
  sourceEnd: 59,
  lineStart: 2,
  lineEnd: 2,
  text: "Timeout: 5000",
};

export const fragment: CompactFragment = {
  id: "fragment:test:timeout",
  text: "timeout=5000ms",
  lineStart: 1,
  lineEnd: 1,
  sourceIds: [source.id],
  sourceSpanIds: [sourceSpan.id],
  mappingType: "one_to_one",
  outputKind: "compact_exact_fact",
  exactness: "byte_exact",
  obligationIds: ["obl:test:timeout"],
  relationIds: ["rel:test:timeout-owner"],
  sourceLabels: ["document evidence · line 2"],
};

const baseCertificate: CertificateData = {
  status: "valid",
  identity: {
    sourceHash: "sha256:test-source",
    normalizedSourceHash: "sha256:test-normalized-source",
    compressedArtifactHash: "sha256:test-compact",
    certificateHash: "sha256:test-certificate",
    queryHash: null,
    tokenizerIdentity: "Fixture byte counter · v1",
    componentVersions: { compiler: "test", verifier: "test" },
  },
  obligations: { verified: 1, discovered: 1, mandatory: 1, denominatorMeaning: "obligations", sourceNote: "test" },
  relations: [{ className: "relation.value_unit_owner", discovered: 1, verified: 1, status: "passed", relationIds: ["rel:test:timeout-owner"] }],
  sourceMap: { verified: 1, discovered: 1, mandatory: 1, denominatorMeaning: "protected items", sourceNote: "test" },
  rules: [{ id: "rule:test:source", severity: "hard", status: "verified", expected: "source evidence", observed: "found", evidenceSpanIds: [sourceSpan.id], recommendation: "none" }],
  failedInvariants: [],
  trustBoundary: ["Compressor proposes.", "Certificate records.", "Verifier recomputes.", "Recovery repairs."],
  note: "Machine-verifiable structural preservation evidence only.",
};

function makeRecovery(): RecoveryData {
  const stages: RecoveryStage[] = Array.from({ length: 10 }, (_, index) => ({
    number: index + 1,
    label: `Stage ${index + 1}`,
    status: index === 3 || index === 4 ? "failed" : index === 5 ? "selected" : index === 8 || index === 9 ? "complete" : "prepared",
    artifactHash: index === 2 || index === 6 || index === 7 ? null : "sha256:test-recovery-artifact",
    effectiveBudget: index === 8 || index === 9 ? 100 : 32,
    action: index >= 5 ? "full_fallback" : "not_recorded",
    count: index === 2 || index === 5 || index === 6 || index === 7 ? null : 100,
    countSource: index === 2 || index === 5 || index === 6 || index === 7 ? null : "fixture_bytes",
    failedInvariants: index === 3 || index === 4 ? ["mandatory_budget_floor"] : [],
    restoredSpans: [],
    verification: index === 8 || index === 9 ? "valid" : index === 3 || index === 4 ? "invalid" : "not_run",
    historyHash: index === 8 || index === 9 ? "sha256:test-recovery-history" : null,
    note: `Prepared stage ${index + 1}.`,
  }));
  return {
    title: "Test fallback",
    sourceFixture: "tests/fixtures/recovery.txt",
    finalAction: "full_fallback",
    finalReduction: makeMetric(0),
    stages,
    rawFailure: "Mandatory evidence cannot fit safely inside requested budget.",
    note: "Exact full context retained; final savings is zero.",
  };
}

export function makeScenario(overrides: Partial<DemoScenario> = {}): DemoScenario {
  const result: DemoScenario["result"] = {
    status: "verified_compressed",
    finalAction: "emit",
    originalSize: makeSize("original", 100),
    rawCompressedSize: makeSize("raw_compressed", 30),
    finalRepairedSize: makeSize("final_repaired", 30),
    requestedReduction: makeMetric(0.7),
    rawReduction: makeMetric(0.7),
    finalReduction: makeMetric(0.7),
    certificateStatus: "valid",
    verificationStatus: "valid",
    tokenizerIdentity: "Fixture byte counter · v1",
    warnings: [],
    synthetic: true,
  };
  return {
    id: "verified-target",
    label: "Verified target compression",
    shortLabel: "A · Verified target",
    description: "A deterministic structural fixture.",
    source,
    compactContext: "timeout=5000ms",
    compactFragments: [fragment],
    sourceSpans: [sourceSpan],
    sourceMap: { available: true, coverage: baseCertificate.sourceMap, mappings: [fragment], note: "test source map" },
    result,
    certificate: baseCertificate,
    recovery: null,
    query: null,
    mode: "target",
    generatedFromCommit: "0ebdd32",
    fixtureIdentity: "tests/fixtures/test.txt",
    evidenceScope: "Committed test fixture; structural evidence only.",
    valuesSynthetic: true,
    targetModelInference: false,
    ...overrides,
  };
}

export function makeBundle(scenarios: DemoScenario[] = [makeScenario()]): DemoBundle {
  const benchmark: BenchmarkData = {
    benchmarkVersion: "ContextProofBench-v1",
    generatedFromCommit: "0ebdd32",
    fixtureIdentity: "reports/runs/phase9-gemini-primary/summary.json",
    metricSource: "configured_tokenizer",
    evidenceScope: "Committed sanitized Phase 9 evidence.",
    valuesSynthetic: false,
    targetModelInference: true,
    itemCount: 50,
    sourceKindDistribution: { document: 10, dialogue: 10, json: 10, log: 10, python: 10 },
    preparedMethodCount: 2,
    preparedMethods: [{ id: "cprgc_target", label: "CPRGC target", lossy: true }],
    expectedRequestCount: 100,
    liveRequestCount: 100,
    tokenizerAccounting: "configured",
    tokenizerIdentity: "tiktoken/cl100k_base@0.13.0",
    pricingStatus: "unset",
    structuralReductionByKind: { document: makeMetric(0.748747, "configured_tokenizer"), dialogue: makeMetric(0.702797, "configured_tokenizer"), json: makeMetric(0.701901, "configured_tokenizer"), log: makeMetric(0.702927, "configured_tokenizer"), python: makeMetric(0, "configured_tokenizer") },
    downstreamRetention: { status: "live_measured", value: 45 / 46 },
    primaryGate: "pass",
    infrastructureStatus: "ready",
    notes: ["Structural demo data is synthetic."],
    futureMetrics: { fullContextAccuracy: 46 / 50, cprgcAccuracy: 45 / 50, pairedRetention: 45 / 46, perSourceRetention: {}, baselineComparison: {}, compression: 0.571274, latency: null, cost: null, failureCounts: {} },
    liveEvidence: {
      modelId: "gemini-3.1-flash-lite",
      successfulRequests: 100,
      infrastructureFailures: 0,
      fullContext: { correct: 46, denominator: 50 },
      cprgc: { correct: 45, denominator: 50 },
      pairedRetention: { correct: 45, denominator: 46, value: 45 / 46, wilsonLow: 0.8866470547848865, wilsonHigh: 0.9961521457419495 },
      perSourceRetention: { dialogue: { correct: 9, denominator: 9 }, document: { correct: 9, denominator: 9 }, json: { correct: 9, denominator: 10 }, log: { correct: 10, denominator: 10 }, python: { correct: 8, denominator: 8 } },
      providerRequestInputReduction: 0.54563862,
      providerUsage: { fullInput: 119699, cprgcInput: 48809, fullOutput: 193, cprgcOutput: 195 },
      emittedContextReduction: 0.714093,
      fallbackAdjustedReduction: 0.571274,
      failureTriage: [{ itemId: "cpb-json-05", category: "missing compact evidence", summary: "Missing compact JSON value." }],
    },
  };
  return { schemaVersion: "ui-demo-v1", generatedAt: "2000-01-01T00:00:00Z", generatedFromCommit: "0ebdd32", mode: "static_demo", scenarios, benchmark, architecture: [], limitations: ["Downstream answer retention is currently unmeasured."] };
}

export function makeFallbackScenario(): DemoScenario {
  const scenario = makeScenario({ id: "recovery-fallback", label: "Recovery fixture / full fallback", shortLabel: "C · Fallback", recovery: makeRecovery(), mode: "aggressive" });
  return { ...scenario, result: { ...scenario.result, status: "verified_fallback", finalAction: "full_fallback", rawReduction: makeMetric(null), finalReduction: makeMetric(0) }, certificate: { ...scenario.certificate, relations: [] } };
}
