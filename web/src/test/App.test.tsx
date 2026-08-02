import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { makeBundle } from "./factories";

function response(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

describe("application routes and primary controls", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/compress");
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(response(makeBundle())));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the landing page and hands off to the workbench", async () => {
    window.history.replaceState({}, "", "/");
    render(<App />);
    expect(screen.getByRole("heading", { name: "Compress context. Keep the evidence." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Try the workbench/ }));
    expect(await screen.findByRole("heading", { name: "Compress context. Verify what remains." })).toBeInTheDocument();
  });

  it("renders every primary route with stable navigation", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Compress context. Verify what remains." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Proof/ }));
    expect(await screen.findByRole("heading", { name: "Verify the compact artifact independently." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Recovery/ }));
    expect(await screen.findByRole("heading", { name: "No recovery was needed" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Benchmarks/ }));
    expect(await screen.findByRole("heading", { name: "Prepared artifacts. No accuracy score yet." })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Architecture/ }));
    expect(await screen.findByRole("region", { name: "TraceFold pipeline" })).toBeInTheDocument();
  });

  it("keeps navigation and primary form controls keyboard reachable", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Compress context. Verify what remains." });
    const proofButton = screen.getByRole("button", { name: /Proof/ });
    const compressButton = screen.getByRole("button", { name: /Compress & verify/ });
    proofButton.focus();
    expect(document.activeElement).toBe(proofButton);
    expect(proofButton).not.toHaveAttribute("tabindex", "-1");
    compressButton.focus();
    expect(document.activeElement).toBe(compressButton);
    expect(compressButton).not.toBeDisabled();
  });

  it("uses the adapter's static fallback result when a backend request fails", async () => {
    const bundle = makeBundle();
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response(bundle))
      .mockRejectedValueOnce(new Error("backend offline"))
      .mockResolvedValueOnce(response(bundle));
    vi.stubGlobal("fetch", fetchImpl);
    render(<App />);
    await screen.findByRole("heading", { name: "Compress context. Verify what remains." });
    fireEvent.click(screen.getByRole("button", { name: /Compress & verify/ }));
    await waitFor(() => expect(screen.getByText(/Static demo/)).toBeInTheDocument());
  });

  it("shows a useful non-blank error state when demo data is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockRejectedValue(new Error("network unavailable")));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Demo evidence could not load" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload demo evidence" })).toBeInTheDocument();
  });
});
