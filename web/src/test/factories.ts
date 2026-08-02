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
    fixtureIdentity: "reports/final/summary.json",
    metricSource: "fixture_bytes",
    evidenceScope: "Committed test report; structural evidence only.",
    valuesSynthetic: true,
    targetModelInference: false,
    itemCount: 50,
    sourceKindDistribution: { document: 10, dialogue: 10, json: 10, log: 10, python: 10 },
    preparedMethodCount: 4,
    preparedMethods: [{ id: "cprgc_target", label: "CPRGC target", lossy: true }],
    expectedRequestCount: 400,
    liveRequestCount: 0,
    tokenizerAccounting: "fixture_only",
    tokenizerIdentity: "Fixture byte counter · v1",
    pricingStatus: "unset",
    structuralReductionByKind: { document: makeMetric(0.7), dialogue: makeMetric(0.7), json: makeMetric(0.7), log: makeMetric(0.7), python: makeMetric(0.7) },
    downstreamRetention: { status: "prepared_only", value: null },
    primaryGate: "unmeasured",
    infrastructureStatus: "ready",
    notes: ["Structural demo data is synthetic."],
    futureMetrics: { fullContextAccuracy: null, cprgcAccuracy: null, pairedRetention: null, perSourceRetention: {}, baselineComparison: {}, compression: null, latency: null, cost: null, failureCounts: {} },
  };
  return { schemaVersion: "ui-demo-v1", generatedAt: "2000-01-01T00:00:00Z", generatedFromCommit: "0ebdd32", mode: "static_demo", scenarios, benchmark, architecture: [], limitations: ["Downstream answer retention is currently unmeasured."] };
}

export function makeFallbackScenario(): DemoScenario {
  const scenario = makeScenario({ id: "recovery-fallback", label: "Recovery fixture / full fallback", shortLabel: "C · Fallback", recovery: makeRecovery(), mode: "aggressive" });
  return { ...scenario, result: { ...scenario.result, status: "verified_fallback", finalAction: "full_fallback", rawReduction: makeMetric(null), finalReduction: makeMetric(0) }, certificate: { ...scenario.certificate, relations: [] } };
}
