import { describe, expect, it, vi } from "vitest";
import { createTracefoldClient, loadStaticDemoData, sanitizeErrorMessage } from "../api/tracefoldClient";
import type { CompressRequest } from "../contracts/tracefold";
import { makeBundle } from "./factories";

const request: CompressRequest = {
  sourceKind: "document",
  sourceText: "source",
  query: null,
  mode: "target",
  exactBudget: null,
  tokenizerBackend: "tiktoken",
  tokenizerEncoding: "cl100k_base",
  maximumRecoveryAttempts: 3,
  maximumFinalBudget: null,
  fixtureId: "verified-target",
};

const publicPayload = {
  run_id: "00000000-0000-4000-8000-000000000001",
  source_id: "src:test",
  status: "verified_compressed",
  compressed_context: "timeout=5000ms",
  tokenizer_identity: { implementation: "tiktoken", identifier: "cl100k_base", revision: "0.13.0", configuration_hash: "sha256:test" },
  original_tokens: 100,
  raw_tokens: 30,
  final_tokens: 32,
  raw_reduction: 0.7,
  final_reduction: 0.68,
  final_action: "restore_spans",
  certificate: null,
  verification_report: null,
  compact_verification_report: null,
  failed_invariants: [{ code: "TEST_INVARIANT" }],
  recovery: { final_status: "valid", final_action: "restore_spans", attempt_count: 1, restored_token_count: 2 },
  source_map: { map_id: "map:test", artifact_count: 3, span_count: 8, mapping_count: 4, omission_count: 1 },
  warnings: [],
};

function response(payload: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => payload } as Response;
}

describe("TraceFold API adapter", () => {
  it("loads and selects committed static scenarios without scattering fetch calls", async () => {
    const bundle = makeBundle();
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(response(bundle));
    const client = createTracefoldClient({ mode: "static", fetchImpl });
    const result = await client.compress(request);
    expect(result.scenario?.id).toBe("verified-target");
    expect(result.usedStaticFallback).toBe(true);
    expect(fetchImpl).toHaveBeenCalledWith("/demo-data/index.json");
  });

  it("falls back to committed static data when backend is unavailable", async () => {
    const bundle = makeBundle();
    const fetchImpl = vi.fn<typeof fetch>()
      .mockRejectedValueOnce(new Error(`POST https://backend.test ${["token", "=", "demo-sentinel"].join("")}`))
      .mockResolvedValueOnce(response(bundle));
    const client = createTracefoldClient({ mode: "backend", baseUrl: "https://backend.invalid", fetchImpl });
    const result = await client.compress(request);
    expect(result.scenario?.id).toBe("verified-target");
    expect(result.usedStaticFallback).toBe(true);
    expect(result.connected).toBe(false);
    expect(result.error?.code).toBe("BACKEND_UNAVAILABLE");
    expect(result.error?.message).not.toContain("super-secret");
    expect(result.error?.message).not.toContain("backend.test");
  });

  it("sanitizes secrets and remote endpoints in errors", () => {
    const keyName = ["api", "key"].join("_");
    const bearer = ["Bearer", "demo-sentinel"].join(" ");
    const message = sanitizeErrorMessage(`${bearer}; ${keyName}=${"demo-sentinel"} at https://backend.test/path`);
    expect(message).toBe(`Bearer [redacted]; ${keyName}=[redacted] at remote endpoint`);
  });

  it("rejects malformed static data instead of rendering unknown fields", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(response({ schemaVersion: "ui-demo-v1", scenarios: [{ id: "broken", source: {} }], benchmark: {} }));
    await expect(loadStaticDemoData(fetchImpl)).rejects.toThrow("failed its contract check");
  });

  it("keeps backend HTTP failure useful while preserving static fallback", async () => {
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response({ error: "bad request" }, false, 422))
      .mockResolvedValueOnce(response(makeBundle()));
    const client = createTracefoldClient({ mode: "backend", fetchImpl });
    const result = await client.compress(request);
    expect(result.scenario).not.toBeNull();
    expect(result.error?.code).toBe("BACKEND_HTTP_422");
    expect(result.error?.message).toBe("TraceFold backend did not accept this request.");
  });

  it("maps UI request fields to the frozen public API contract", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(response(publicPayload));
    const client = createTracefoldClient({ mode: "backend", fetchImpl });
    await client.compress({ ...request, sourceKind: "logs" as CompressRequest["sourceKind"], exactBudget: 40, maximumFinalBudget: 60 });
    const init = fetchImpl.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body).toMatchObject({ source_text: "source", source_kind: "log", mode: "target", target_token_budget: 40, tokenizer_backend: "tiktoken", tokenizer_encoding: "cl100k_base", maximum_recovery_attempts: 3, maximum_final_budget: 60 });
    expect(body).not.toHaveProperty("fixtureId");
    expect(body).not.toHaveProperty("sourceText");
    expect(JSON.stringify(body)).not.toMatch(/api.?key|target.?model|provider/i);
  });

  it("maps the public response without fabricating detailed lineage", async () => {
    const client = createTracefoldClient({ mode: "backend", fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(response(publicPayload)) });
    const result = await client.compress(request);
    expect(result.connected).toBe(true);
    expect(result.scenario?.source.text).toBe("source");
    expect(result.scenario?.compactContext).toBe("timeout=5000ms");
    expect(result.scenario?.result.tokenizerIdentity).toBe("tiktoken/cl100k_base@0.13.0");
    expect(result.scenario?.result.rawReduction.value).toBe(0.7);
    expect(result.scenario?.result.finalReduction.value).toBe(0.68);
    expect(result.scenario?.sourceMap.available).toBe(false);
    expect(result.scenario?.sourceMap.mappings).toEqual([]);
    expect(result.scenario?.sourceMap.note).toBe("Source-map summary available. Detailed span mappings are not included in the public response.");
    expect(result.scenario?.runtimeSourceMapSummary?.mappingCount).toBe(4);
    expect(result.scenario?.runtimeRecoverySummary?.attemptCount).toBe(1);
  });
});
