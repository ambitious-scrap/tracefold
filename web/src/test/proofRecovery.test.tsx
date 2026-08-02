import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProofView } from "../components/ProofView";
import { RecoveryView } from "../components/RecoveryView";
import { makeFallbackScenario, makeScenario } from "./factories";

describe("proof and recovery views", () => {
  it("renders zero relation coverage as not applicable", () => {
    const scenario = makeScenario({ certificate: { ...makeScenario().certificate, relations: [] } });
    render(<ProofView scenario={scenario} />);
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
    expect(screen.getByText("Machine-verifiable structural preservation evidence only.")).toBeInTheDocument();
  });

  it("wraps long certificate hashes and renders unavailable identity fields safely", () => {
    const scenario = makeScenario({ certificate: { ...makeScenario().certificate, identity: { ...makeScenario().certificate.identity, sourceHash: `sha256:${"a".repeat(256)}`, certificateHash: null } } });
    render(<ProofView scenario={scenario} />);
    expect(screen.getByLabelText(/Source hash:/)).toHaveTextContent("sha256:");
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });

  it("keeps the ten recovery stages ordered and exposes failed invariants", () => {
    render(<RecoveryView scenario={makeFallbackScenario()} />);
    const labels = [...document.querySelectorAll(".timeline-item__label")].map((node) => node.textContent);
    expect(labels).toEqual(["Stage 1", "Stage 2", "Stage 3", "Stage 4", "Stage 5", "Stage 6", "Stage 7", "Stage 8", "Stage 9", "Stage 10"]);
    expect(screen.getAllByText("mandatory_budget_floor").length).toBeGreaterThan(0);
    expect(screen.getByText("Zero final savings")).toBeInTheDocument();
    expect(screen.getByText("0.0%")).toBeInTheDocument();
    expect(screen.getByText("Structural byte reduction")).toBeInTheDocument();
  });

  it("shows a safe empty state when a scenario has no recovery event", () => {
    render(<RecoveryView scenario={makeScenario()} />);
    expect(screen.getByRole("heading", { name: "No recovery was needed" })).toBeInTheDocument();
  });
});
