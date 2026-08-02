import type {
  CertificateData,
  ClientError,
  CompressRequest,
  CompressResponse,
  CoverageMetric,
  DemoBundle,
  DemoScenario,
  FinalAction,
  RelationCoverage,
  VerificationStatus,
} from "../contracts/tracefold";

export type ClientMode = "static" | "backend";

export interface TracefoldClient {
  readonly mode: ClientMode;
  loadDemoData(): Promise<DemoBundle>;
  compress(request: CompressRequest): Promise<CompressResponse>;
}

export interface TracefoldClientOptions {
  mode?: ClientMode;
  baseUrl?: string;
  demoPath?: string;
  fetchImpl?: typeof fetch;
}

interface PublicCompressionResponse {
  run_id: string;
  source_id: string;
  status: DemoScenario["result"]["status"];
  compressed_context: string;
  tokenizer_identity: Record<string, unknown>;
  original_tokens: number;
  raw_tokens: number | null;
  final_tokens: number | null;
  raw_reduction: number | null;
  final_reduction: number | null;
  final_action: FinalAction;
  certificate: Record<string, unknown> | null;
  verification_report: Record<string, unknown> | null;
  compact_verification_report: Record<string, unknown> | null;
  failed_invariants: unknown[];
  recovery: Record<string, unknown>;
  source_map: Record<string, unknown>;
  warnings: string[];
}

const DEFAULT_DEMO_PATH = "/demo-data/index.json";
const DEFAULT_BASE_URL = import.meta.env.VITE_TRACEFOLD_API_URL ?? "";

export function createTracefoldClient(options: TracefoldClientOptions = {}): TracefoldClient {
  const mode = options.mode ?? (import.meta.env.VITE_TRACEFOLD_API_MODE === "backend" ? "backend" : "static");
  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
  const demoPath = options.demoPath ?? DEFAULT_DEMO_PATH;

  async function loadDemoData(): Promise<DemoBundle> {
    const response = await fetchImpl(demoPath);
    if (!response.ok) throw new Error(`Static demo data unavailable (${response.status}).`);
    const payload = (await response.json()) as unknown;
    if (!isDemoBundle(payload)) throw new Error("Static demo data failed its contract check.");
    return payload;
  }

  async function compress(request: CompressRequest): Promise<CompressResponse> {
    if (mode === "static") {
      try {
        const bundle = await loadDemoData();
        return { scenario: selectScenario(bundle, request), error: null, connected: false, usedStaticFallback: true };
      } catch (error) {
        return { scenario: null, error: toClientError(error, "DEMO_DATA_UNAVAILABLE"), connected: false, usedStaticFallback: false };
      }
    }

    try {
      const response = await fetchImpl(`${baseUrl}/v1/compress`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(toPublicRequest(request)),
      });
      if (!response.ok) {
        return fallbackFromBackend(request, { code: `BACKEND_HTTP_${response.status}`, message: "TraceFold backend did not accept this request.", recoverable: true });
      }
      const payload = (await response.json()) as unknown;
      if (!isPublicCompressionResponse(payload)) throw new Error("Backend response failed its public contract check.");
      return { scenario: mapPublicResponse(payload, request), error: null, connected: true, usedStaticFallback: false };
    } catch (error) {
      return fallbackFromBackend(request, toClientError(error, "BACKEND_UNAVAILABLE"));
    }
  }

  async function fallbackFromBackend(request: CompressRequest, backendError: ClientError): Promise<CompressResponse> {
    try {
      const bundle = await loadDemoData();
      return { scenario: selectScenario(bundle, request), error: backendError, connected: false, usedStaticFallback: true };
    } catch {
      return { scenario: null, error: backendError, connected: false, usedStaticFallback: false };
    }
  }

  return { mode, loadDemoData, compress };
}

export function toPublicRequest(request: CompressRequest): Record<string, unknown> {
  return {
    source_text: request.sourceText,
    source_kind: String(request.sourceKind) === "logs" ? "log" : request.sourceKind,
    media_type: request.sourceKind === "json" ? "application/json" : "text/plain",
    mode: request.mode,
    target_token_budget: request.exactBudget,
    query: request.query,
    tokenizer_backend: request.tokenizerBackend || "tiktoken",
    tokenizer_encoding: request.tokenizerEncoding || "cl100k_base",
    maximum_recovery_attempts: request.maximumRecoveryAttempts || 3,
    maximum_final_budget: request.maximumFinalBudget,
  };
}

export async function loadStaticDemoData(fetchImpl: typeof fetch = fetch, demoPath = DEFAULT_DEMO_PATH): Promise<DemoBundle> {
  const response = await fetchImpl(demoPath);
  if (!response.ok) throw new Error(`Static demo data unavailable (${response.status}).`);
  const payload = (await response.json()) as unknown;
  if (!isDemoBundle(payload)) throw new Error("Static demo data failed its contract check.");
  return payload;
}

function selectScenario(bundle: DemoBundle, request: CompressRequest): DemoScenario {
  const exact = bundle.scenarios.find((item) => item.id === request.fixtureId);
  if (exact) return exact;
  const byMode = bundle.scenarios.find((item) => item.mode === request.mode && item.source.kind === request.sourceKind);
  return byMode ?? bundle.scenarios[0];
}

function mapPublicResponse(payload: PublicCompressionResponse, request: CompressRequest): DemoScenario {
  const tokenizer = tokenizerLabel(payload.tokenizer_identity);
  const failedInvariants = payload.failed_invariants.map(failedInvariantLabel);
  const verification = payload.verification_report;
  const verificationStatus = statusValue(verification?.status);
  const sourceMapCoverage = recordValue(verification?.source_map_coverage);
  const obligationResults = recordValue(verification?.obligation_results);
  const relations = arrayValue(verification?.relation_results).map(mapRelation).filter((item): item is RelationCoverage => item !== null);
  const certificate = mapCertificate(payload, tokenizer, verificationStatus, obligationResults, sourceMapCoverage, relations, failedInvariants);
  const compactStatus = statusValue(payload.compact_verification_report?.status);
  const warnings = [...payload.warnings];
  if (compactStatus !== "not_run" && compactStatus !== "valid") warnings.push(`Compact verification: ${compactStatus}.`);

  return {
    id: "verified-target",
    label: payload.status === "incompressible" ? "Incompressible at protected mandatory floor" : "Runtime compression result",
    shortLabel: "Runtime result",
    description: payload.status === "incompressible"
      ? "TraceFold retained the full source rather than remove protected evidence."
      : "Generated locally by POST /v1/compress; no target-model request occurred.",
    source: {
      id: payload.source_id,
      label: "Submitted source",
      kind: request.sourceKind,
      text: request.sourceText,
      hash: stringValue(verification?.verified_source_hash) ?? "Not included in public response",
      generatedFrom: "POST /v1/compress request",
    },
    compactContext: payload.compressed_context,
    compactFragments: [],
    sourceSpans: [],
    sourceMap: {
      available: false,
      coverage: coverageFrom(sourceMapCoverage, "public source-map summary"),
      mappings: [],
      note: "Source-map summary available. Detailed span mappings are not included in the public response.",
    },
    result: {
      status: payload.status,
      finalAction: payload.final_action,
      originalSize: size("original", request.sourceText, payload.original_tokens, tokenizer),
      rawCompressedSize: size("raw_compressed", payload.compressed_context, payload.raw_tokens, tokenizer),
      finalRepairedSize: size("final_repaired", payload.compressed_context, payload.final_tokens, tokenizer),
      requestedReduction: metric(request.exactBudget === null ? modeReduction(request.mode) : null, "raw", tokenizer),
      rawReduction: metric(payload.raw_reduction, "raw", tokenizer),
      finalReduction: metric(payload.status === "incompressible" ? null : payload.final_reduction, "final", tokenizer),
      certificateStatus: certificate.status,
      verificationStatus,
      tokenizerIdentity: tokenizer,
      warnings,
      synthetic: false,
    },
    certificate,
    recovery: null,
    query: request.query,
    mode: request.mode,
    generatedFromCommit: "runtime",
    fixtureIdentity: `run ${payload.run_id}`,
    evidenceScope: "Local public compression API response; structural evidence only.",
    valuesSynthetic: false,
    targetModelInference: false,
    runtimeSourceMapSummary: {
      mapId: nullableString(payload.source_map.map_id),
      artifactCount: numberValue(payload.source_map.artifact_count) ?? 0,
      spanCount: numberValue(payload.source_map.span_count) ?? 0,
      mappingCount: numberValue(payload.source_map.mapping_count) ?? 0,
      omissionCount: numberValue(payload.source_map.omission_count) ?? 0,
    },
    runtimeRecoverySummary: {
      finalStatus: nullableString(payload.recovery.final_status),
      finalAction: payload.final_action,
      attemptCount: numberValue(payload.recovery.attempt_count) ?? 0,
      restoredTokenCount: numberValue(payload.recovery.restored_token_count) ?? 0,
    },
  };
}

function mapCertificate(
  payload: PublicCompressionResponse,
  tokenizer: string,
  status: VerificationStatus,
  obligationResults: Record<string, unknown>,
  sourceMapCoverage: Record<string, unknown>,
  relations: RelationCoverage[],
  failedInvariants: string[],
): CertificateData {
  const candidate = payload.certificate ?? {};
  const certificate = recordValue(candidate.certificate);
  const componentVersions = recordValue(certificate.component_versions);
  const rules = Object.entries(obligationResults).map(([id, raw]) => {
    const value = recordValue(raw);
    const discovered = numberValue(value.discovered) ?? 0;
    const verified = numberValue(value.verified) ?? 0;
    const applicability = stringValue(value.applicability);
    return {
      id,
      severity: "hard" as const,
      status: applicability === "applicable" ? (discovered === verified ? "verified" as const : "failed" as const) : "not_applicable" as const,
      expected: `${discovered} discovered obligation${discovered === 1 ? "" : "s"}`,
      observed: `${verified} independently verified`,
      evidenceSpanIds: [],
      recommendation: discovered === verified ? "None." : "Preserve missing source evidence or return full context.",
    };
  });
  return {
    status,
    identity: {
      sourceHash: nullableString(payload.verification_report?.verified_source_hash),
      normalizedSourceHash: nullableString(candidate.normalized_source_hash),
      compressedArtifactHash: nullableString(payload.verification_report?.verified_compressed_artifact_hash),
      certificateHash: nullableString(candidate.certificate_hash),
      queryHash: nullableString(payload.verification_report?.verified_query_hash),
      tokenizerIdentity: tokenizer,
      componentVersions: Object.fromEntries(Object.entries(componentVersions).filter((entry): entry is [string, string] => typeof entry[1] === "string")),
    },
    obligations: aggregateCoverage(obligationResults),
    relations,
    sourceMap: coverageFrom(sourceMapCoverage, "public verification report"),
    rules,
    failedInvariants,
    trustBoundary: ["Compressor proposes.", "Certificate records.", "Verifier recomputes.", "Recovery repairs."],
    note: "Machine-verifiable structural preservation evidence. This does not prove semantic equivalence.",
  };
}

function isPublicCompressionResponse(value: unknown): value is PublicCompressionResponse {
  if (!isRecord(value)) return false;
  return typeof value.run_id === "string"
    && typeof value.source_id === "string"
    && isResultStatus(value.status)
    && typeof value.compressed_context === "string"
    && isRecord(value.tokenizer_identity)
    && typeof value.original_tokens === "number"
    && nullableNumber(value.raw_tokens)
    && nullableNumber(value.final_tokens)
    && nullableNumber(value.raw_reduction)
    && nullableNumber(value.final_reduction)
    && isFinalAction(value.final_action)
    && (value.certificate === null || isRecord(value.certificate))
    && (value.verification_report === null || isRecord(value.verification_report))
    && (value.compact_verification_report === null || isRecord(value.compact_verification_report))
    && Array.isArray(value.failed_invariants)
    && isRecord(value.recovery)
    && isRecord(value.source_map)
    && Array.isArray(value.warnings)
    && value.warnings.every((item) => typeof item === "string");
}

function isDemoBundle(value: unknown): value is DemoBundle {
  if (!isRecord(value)) return false;
  return value.schemaVersion === "ui-demo-v1" && Array.isArray(value.scenarios) && value.scenarios.length > 0 && value.scenarios.every(isDemoScenario) && isRecord(value.benchmark);
}

function isDemoScenario(value: unknown): value is DemoScenario {
  return isRecord(value) && typeof value.id === "string" && isRecord(value.source) && typeof value.source.text === "string" && isRecord(value.result);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function recordValue(value: unknown): Record<string, unknown> { return isRecord(value) ? value : {}; }
function arrayValue(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function stringValue(value: unknown): string | null { return typeof value === "string" ? value : null; }
function nullableString(value: unknown): string | null { return value === null || value === undefined ? null : stringValue(value); }
function numberValue(value: unknown): number | null { return typeof value === "number" && Number.isFinite(value) ? value : null; }
function nullableNumber(value: unknown): boolean { return value === null || numberValue(value) !== null; }

function isFinalAction(value: unknown): value is FinalAction {
  return value === "emit" || value === "restore_spans" || value === "expand_budget" || value === "full_fallback";
}

function isResultStatus(value: unknown): value is DemoScenario["result"]["status"] {
  return value === "verified_compressed" || value === "verified_repaired" || value === "verified_fallback" || value === "incompressible" || value === "failed" || value === "prepared_only";
}

function statusValue(value: unknown): VerificationStatus {
  if (value === "valid" || value === "invalid" || value === "unverifiable" || value === "not_run") return value;
  return value === null || value === undefined ? "not_run" : "unverifiable";
}

function tokenizerLabel(value: Record<string, unknown>): string {
  const implementation = stringValue(value.implementation) ?? "unknown";
  const identifier = stringValue(value.identifier) ?? "unknown";
  const revision = stringValue(value.revision);
  return `${implementation}/${identifier}${revision ? `@${revision}` : ""}`;
}

function metric(value: number | null, scope: "raw" | "final", tokenizer: string) {
  return { value, source: "configured_tokenizer" as const, scope, counterIdentity: tokenizer, modelIdentity: null, synthetic: false };
}

function size(label: "original" | "raw_compressed" | "final_repaired", text: string, tokens: number | null, tokenizer: string) {
  return { label, bytes: new TextEncoder().encode(text).length, tokens: { value: tokens, source: "configured_tokenizer" as const, counterIdentity: tokenizer, synthetic: false } };
}

function modeReduction(mode: CompressRequest["mode"]): number {
  return mode === "conservative" ? 0.5 : mode === "aggressive" ? 0.8 : 0.7;
}

function failedInvariantLabel(value: unknown): string {
  if (typeof value === "string") return value;
  if (isRecord(value)) return stringValue(value.code) ?? stringValue(value.invariant_id) ?? "unidentified invariant";
  return "unidentified invariant";
}

function aggregateCoverage(results: Record<string, unknown>): CoverageMetric {
  let discovered = 0;
  let verified = 0;
  for (const value of Object.values(results)) {
    const result = recordValue(value);
    discovered += numberValue(result.discovered) ?? 0;
    verified += numberValue(result.verified) ?? 0;
  }
  return { verified, discovered, mandatory: null, denominatorMeaning: "discovered obligations", sourceNote: "Public verification report." };
}

function coverageFrom(value: Record<string, unknown>, note: string): CoverageMetric {
  return {
    verified: numberValue(value.protected_items_with_valid_map),
    discovered: numberValue(value.protected_items),
    mandatory: null,
    denominatorMeaning: "protected source-map items",
    sourceNote: note,
  };
}

function mapRelation(raw: unknown): RelationCoverage | null {
  const value = recordValue(raw);
  const className = stringValue(value.class_name);
  if (!className) return null;
  const discovered = numberValue(value.discovered);
  const verified = numberValue(value.verified);
  const rawStatus = stringValue(value.status);
  const status: RelationCoverage["status"] = discovered === 0 ? "not_applicable" : rawStatus === "passed" ? "passed" : rawStatus === "failed" ? "failed" : "indeterminate";
  return { className, discovered, verified, status, relationIds: [] };
}

function toClientError(error: unknown, code: string): ClientError {
  const message = error instanceof Error ? error.message : "The request could not be completed.";
  return { code, message: sanitizeErrorMessage(message), recoverable: true };
}

export function sanitizeErrorMessage(message: string): string {
  return message
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer [redacted]")
    .replace(/((?:api[_-]?key|token|secret))\s*[=:]\s*[^\s,;]+/gi, "$1=[redacted]")
    .replace(/https?:\/\/[^\s)]+/gi, "remote endpoint");
}

export const staticDemoPath = DEFAULT_DEMO_PATH;
