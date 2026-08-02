import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import generated from "../../public/demo-data/index.json";
import { BenchmarksView } from "../components/BenchmarksView";
import type { DemoBundle } from "../contracts/tracefold";

describe("frozen Phase 9 evidence", () => {
  it("renders exact paired, absolute, compression, and limitation evidence", () => {
    const bundle = generated as unknown as DemoBundle;
    render(<BenchmarksView benchmark={bundle.benchmark} />);
    expect(screen.getByRole("heading", { name: "Retained 45 of 46 answers the full context answered correctly" })).toBeInTheDocument();
    expect(screen.getByText("46/50")).toBeInTheDocument();
    expect(screen.getByText("45/50")).toBeInTheDocument();
    expect(screen.getByText(/Wilson 95% interval: 88\.6647% to 99\.6152%/)).toBeInTheDocument();
    expect(screen.getByText("71.4093%")).toBeInTheDocument();
    expect(screen.getByText("57.1274%")).toBeInTheDocument();
    expect(screen.getByText("54.563862%")).toBeInTheDocument();
    expect(screen.getByText("Not configured")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Incompressible at protected mandatory floor" })).toBeInTheDocument();
    expect(screen.getByText("cpb-json-05")).toBeInTheDocument();
    expect(screen.queryByText(/98% accuracy/i)).not.toBeInTheDocument();
  });
});
