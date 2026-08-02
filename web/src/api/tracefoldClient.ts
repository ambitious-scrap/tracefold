import type {
  ClientError,
  CompressRequest,
  CompressResponse,
  DemoBundle,
  DemoScenario,
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

const DEFAULT_DEMO_PATH = "/demo-data/index.json";
const DEFAULT_BASE_URL = import.meta.env.VITE_TRACEFOLD_API_URL ?? "";

export function createTracefoldClient(options: TracefoldClientOptions = {}): TracefoldClient {
  const mode = options.mode ?? (import.meta.env.VITE_TRACEFOLD_API_MODE === "backend" ? "backend" : "static");
  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = options.baseUrl ?? DEFAULT_BASE_URL;
  const demoPath = options.demoPath ?? DEFAULT_DEMO_PATH;

  async function loadDemoData(): Promise<DemoBundle> {
    const response = await fetchImpl(demoPath);
    if (!response.ok) {
      throw new Error(`Static demo data unavailable (${response.status}).`);
    }
    const payload = (await response.json()) as unknown;
    if (!isDemoBundle(payload)) throw new Error("Static demo data failed its contract check.");
    return payload;
  }

  async function compress(request: CompressRequest): Promise<CompressResponse> {
    if (mode === "static") {
      try {
        const bundle = await loadDemoData();
        return {
          scenario: selectScenario(bundle, request),
          error: null,
          connected: false,
          usedStaticFallback: true,
        };
      } catch (error) {
        return { scenario: null, error: toClientError(error, "DEMO_DATA_UNAVAILABLE"), connected: false, usedStaticFallback: false };
      }
    }

    try {
      const response = await fetchImpl(`${baseUrl}/v1/compress`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        return fallbackFromBackend(request, { code: `BACKEND_HTTP_${response.status}`, message: "TraceFold backend did not accept this request.", recoverable: true });
      }
      const mapped = mapBackendResponse((await response.json()) as Record<string, unknown>);
      return { scenario: mapped, error: null, connected: true, usedStaticFallback: false };
    } catch (error) {
      return fallbackFromBackend(request, toClientError(error, "BACKEND_UNAVAILABLE"));
    }
  }

  async function fallbackFromBackend(request: CompressRequest, backendError: ClientError): Promise<CompressResponse> {
    try {
      const bundle = await loadDemoData();
      return {
        scenario: selectScenario(bundle, request),
        error: backendError,
        connected: false,
        usedStaticFallback: true,
      };
    } catch {
      return { scenario: null, error: backendError, connected: false, usedStaticFallback: false };
    }
  }

  return { mode, loadDemoData, compress };
}

export async function loadStaticDemoData(
  fetchImpl: typeof fetch = fetch,
  demoPath = DEFAULT_DEMO_PATH,
): Promise<DemoBundle> {
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

function mapBackendResponse(payload: Record<string, unknown>): DemoScenario {
  const candidate = payload.demo_scenario ?? payload.scenario ?? payload;
  if (!isDemoScenario(candidate)) {
    throw new Error("Backend response did not include a mapped TraceFold scenario.");
  }
  return candidate;
}

function isDemoBundle(value: unknown): value is DemoBundle {
  if (!isRecord(value)) return false;
  return value.schemaVersion === "ui-demo-v1" && Array.isArray(value.scenarios) && value.scenarios.length > 0 && value.scenarios.every(isDemoScenario) && isRecord(value.benchmark);
}

function isDemoScenario(value: unknown): value is DemoScenario {
  if (!isRecord(value)) return false;
  return typeof value.id === "string" && isRecord(value.source) && typeof value.source.text === "string" && isRecord(value.result);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function toClientError(error: unknown, code: string): ClientError {
  const message = error instanceof Error ? error.message : "The request could not be completed.";
  return {
    code,
    message: sanitizeErrorMessage(message),
    recoverable: true,
  };
}

export function sanitizeErrorMessage(message: string): string {
  return message
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, "Bearer [redacted]")
    .replace(/((?:api[_-]?key|token|secret))\s*[=:]\s*[^\s,;]+/gi, "$1=[redacted]")
    .replace(/https?:\/\/[^\s)]+/gi, "remote endpoint");
}

export const staticDemoPath = DEFAULT_DEMO_PATH;
