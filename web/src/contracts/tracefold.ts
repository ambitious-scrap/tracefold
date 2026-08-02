export type SourceKind = "document" | "dialogue" | "json" | "log" | "python";
export type CompressionMode = "conservative" | "target" | "aggressive";
export type MetricSource = "fixture_bytes" | "configured_tokenizer" | "provider_usage";
export type MetricScope = "raw" | "final" | "provider";
export type DownstreamStatus =
  | "unmeasured"
  | "prepared_only"
  | "replay_measured"
  | "live_measured";
export type VerificationStatus = "valid" | "invalid" | "unverifiable" | "not_run";
export type FinalAction = "emit" | "restore_spans" | "expand_budget" | "full_fallback";
export type ScenarioId = "verified-target" | "aggressive-incompressible" | "recovery-fallback" | "prepared-benchmark";
export type MappingType = "one_to_one" | "one_to_many" | "many_to_one";
export type OutputKind =
  | "exact_copy"
  | "compact_exact_fact"
  | "compact_exact_relation"
  | "deterministic_aggregate"
  | "synthesized_marker"
  | "restored_span";

export interface ReductionMetric {
  value: number | null;
  source: MetricSource;
  scope: MetricScope;
  counterIdentity: string;
  modelIdentity: string | null;
  synthetic: boolean;
}

export interface CountMetric {
  value: number | null;
  source: MetricSource;
  counterIdentity: string;
  synthetic: boolean;
}

export interface ArtifactSize {
  bytes: number | null;
  tokens: CountMetric | null;
  label: "original" | "raw_compressed" | "final_repaired";
}

export interface CoverageMetric {
  verified: number | null;
  discovered: number | null;
  mandatory: number | null;
  denominatorMeaning: string;
  sourceNote: string;
}

export interface SourceDocument {
  id: string;
  label: string;
  kind: SourceKind;
  text: string;
  hash: string;
  generatedFrom: string;
}

export interface CompactFragment {
  id: string;
  text: string;
  lineStart: number;
  lineEnd: number;
  sourceIds: string[];
  sourceSpanIds: string[];
  mappingType: MappingType;
  outputKind: OutputKind;
  exactness: "byte_exact" | "structurally_equivalent" | "semantic_lineage_only";
  obligationIds: string[];
  relationIds: string[];
  sourceLabels: string[];
}

export interface SourceSpan {
  id: string;
  sourceId: string;
  sourceStart: number;
  sourceEnd: number;
  lineStart: number;
  lineEnd: number;
  text: string;
}

export interface SourceMapSummary {
  available: boolean;
  coverage: CoverageMetric;
  mappings: CompactFragment[];
  note: string;
}

export interface ObligationRule {
  id: string;
  severity: "hard" | "soft";
  status: "verified" | "failed" | "not_applicable" | "unreported";
  expected: string;
  observed: string;
  evidenceSpanIds: string[];
  recommendation: string;
}

export interface RelationCoverage {
  className: string;
  discovered: number | null;
  verified: number | null;
  status: "passed" | "failed" | "indeterminate" | "not_applicable" | "unreported";
  relationIds: string[];
}

export interface CertificateIdentity {
  sourceHash: string | null;
  normalizedSourceHash: string | null;
  compressedArtifactHash: string | null;
  certificateHash: string | null;
  queryHash: string | null;
  tokenizerIdentity: string;
  componentVersions: Record<string, string>;
}

export interface CertificateData {
  status: VerificationStatus;
  identity: CertificateIdentity;
  obligations: CoverageMetric;
  relations: RelationCoverage[];
  sourceMap: CoverageMetric;
  rules: ObligationRule[];
  failedInvariants: string[];
  trustBoundary: string[];
  note: string;
}

export interface RecoveryStage {
  number: number;
  label: string;
  status: "complete" | "failed" | "selected" | "not_reached" | "prepared";
  artifactHash: string | null;
  effectiveBudget: number | null;
  action: FinalAction | "not_recorded";
  count: number | null;
  countSource: MetricSource | null;
  failedInvariants: string[];
  restoredSpans: string[];
  verification: VerificationStatus;
  historyHash: string | null;
  note: string;
}

export interface RecoveryData {
  title: string;
  sourceFixture: string;
  finalAction: FinalAction;
  finalReduction: ReductionMetric;
  stages: RecoveryStage[];
  rawFailure: string;
  note: string;
}

export interface ResultSummary {
  status: "verified_compressed" | "verified_repaired" | "verified_fallback" | "incompressible" | "failed" | "prepared_only";
  finalAction: FinalAction;
  originalSize: ArtifactSize;
  rawCompressedSize: ArtifactSize;
  finalRepairedSize: ArtifactSize;
  requestedReduction: ReductionMetric;
  rawReduction: ReductionMetric;
  finalReduction: ReductionMetric;
  certificateStatus: VerificationStatus;
  verificationStatus: VerificationStatus;
  tokenizerIdentity: string;
  warnings: string[];
  synthetic: boolean;
}

export interface DemoScenario {
  id: ScenarioId;
  label: string;
  shortLabel: string;
  description: string;
  source: SourceDocument;
  compactContext: string;
  compactFragments: CompactFragment[];
  sourceSpans: SourceSpan[];
  sourceMap: SourceMapSummary;
  result: ResultSummary;
  certificate: CertificateData;
  recovery: RecoveryData | null;
  query: string | null;
  mode: CompressionMode;
  generatedFromCommit: string;
  fixtureIdentity: string;
  evidenceScope: string;
  valuesSynthetic: boolean;
  targetModelInference: boolean;
}

export interface BenchmarkData {
  benchmarkVersion: string;
  generatedFromCommit: string;
  fixtureIdentity: string;
  metricSource: MetricSource;
  evidenceScope: string;
  valuesSynthetic: boolean;
  targetModelInference: boolean;
  itemCount: number;
  sourceKindDistribution: Record<SourceKind, number>;
  preparedMethodCount: number;
  preparedMethods: { id: string; label: string; lossy: boolean }[];
  expectedRequestCount: number;
  liveRequestCount: number;
  tokenizerAccounting: "fixture_only" | "configured" | "provider_reported" | "unavailable";
  tokenizerIdentity: string;
  pricingStatus: "unset" | "configured";
  structuralReductionByKind: Record<SourceKind, ReductionMetric>;
  downstreamRetention: { status: DownstreamStatus; value: number | null };
  primaryGate: "pass" | "fail" | "unmeasured";
  infrastructureStatus: "ready" | "degraded" | "blocked";
  notes: string[];
  futureMetrics: {
    fullContextAccuracy: number | null;
    cprgcAccuracy: number | null;
    pairedRetention: number | null;
    perSourceRetention: Record<string, number>;
    baselineComparison: Record<string, number>;
    compression: number | null;
    latency: number | null;
    cost: number | null;
    failureCounts: Record<string, number>;
  };
}

export interface ArchitectureStage {
  id: string;
  label: string;
  input: string;
  output: string;
  responsibility: string;
  trustDomain: "compressor" | "verifier" | "recovery" | "target_evaluation";
  failureBehavior: string;
}

export interface DemoBundle {
  schemaVersion: "ui-demo-v1";
  generatedAt: string;
  generatedFromCommit: string;
  mode: "static_demo";
  scenarios: DemoScenario[];
  benchmark: BenchmarkData;
  architecture: ArchitectureStage[];
  limitations: string[];
}

export interface CompressRequest {
  sourceKind: SourceKind;
  sourceText: string;
  query: string | null;
  mode: CompressionMode;
  exactBudget: number | null;
  tokenizerIdentity: string;
  maximumRecoveryAttempts: number;
  fixtureId: string;
}

export interface ClientError {
  code: string;
  message: string;
  recoverable: boolean;
}

export interface CompressResponse {
  scenario: DemoScenario | null;
  error: ClientError | null;
  connected: boolean;
  usedStaticFallback: boolean;
}

export const sourceKindLabels: Record<SourceKind, string> = {
  document: "Document",
  dialogue: "Dialogue",
  json: "JSON",
  log: "Logs",
  python: "Python",
};

export function metricSourceLabel(source: MetricSource): string {
  if (source === "fixture_bytes") return "Fixture bytes";
  if (source === "configured_tokenizer") return "Configured tokenizer";
  return "Provider usage";
}

export function reductionLabel(metric: ReductionMetric): string {
  if (metric.source === "fixture_bytes") return "Structural byte reduction";
  if (metric.source === "configured_tokenizer") {
    return `Token reduction · ${metric.counterIdentity}`;
  }
  return `Provider-reported input-token reduction · ${metric.modelIdentity ?? "model not declared"}`;
}

export function formatReduction(metric: ReductionMetric): string {
  return metric.value === null ? "Unmeasured" : `${(metric.value * 100).toFixed(1)}%`;
}

export function retentionLabel(retention: { status: DownstreamStatus; value: number | null }): string {
  if (retention.value === null || retention.status === "unmeasured") {
    return retention.status === "prepared_only" ? "Prepared only" : "Unmeasured";
  }
  return `${(retention.value * 100).toFixed(1)}%`;
}

export function coverageLabel(metric: CoverageMetric): string {
  if (metric.discovered === 0) return "Not applicable";
  if (metric.discovered === null || metric.verified === null) return "Unreported";
  return `${metric.verified}/${metric.discovered}`;
}

export function coveragePercent(metric: CoverageMetric): string {
  if (metric.discovered === 0) return "Not applicable";
  if (metric.discovered === null || metric.verified === null) return "Unreported";
  return `${Math.round((metric.verified / metric.discovered) * 100)}%`;
}

export function displayCount(metric: CountMetric | null): string {
  if (!metric || metric.value === null) return "Unmeasured";
  return metric.value.toLocaleString("en-US");
}

export function hashLabel(hash: string | null): string {
  return hash ? hash : "Not available";
}

export function isFallbackScenario(scenario: DemoScenario): boolean {
  return scenario.result.finalAction === "full_fallback" || scenario.result.status === "verified_fallback";
}
