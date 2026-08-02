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
  tokenizerIdentity: "Fixture byte counter · v1",
  maximumRecoveryAttempts: 3,
  fixtureId: "verified-target",
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
});
