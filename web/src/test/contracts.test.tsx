import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  coverageLabel,
  coveragePercent,
  formatReduction,
  isFallbackScenario,
  metricSourceLabel,
  reductionLabel,
  retentionLabel,
} from "../contracts/tracefold";
import { BenchmarksView } from "../components/BenchmarksView";
import { MetricStrip } from "../components/MetricStrip";
import { statusTone } from "../components/statusTone";
import { makeBundle, makeMetric, makeScenario } from "./factories";

describe("metric-source safety", () => {
  it("uses distinct labels for fixture, configured, and provider sources", () => {
    expect(metricSourceLabel("fixture_bytes")).toBe("Fixture bytes");
    expect(reductionLabel(makeMetric(0.7, "fixture_bytes"))).toBe("Structural byte reduction");
    expect(reductionLabel({ ...makeMetric(0.7, "configured_tokenizer"), counterIdentity: "cl100k_base" })).toBe("Token reduction · cl100k_base");
    expect(reductionLabel({ ...makeMetric(0.7, "provider_usage"), modelIdentity: "gpt-demo" })).toBe("Provider-reported input-token reduction · gpt-demo");
  });

  it("never labels fixture-byte reduction as tokens in the metric strip", () => {
    const scenario = makeScenario();
    render(<MetricStrip original={scenario.result.originalSize} raw={scenario.result.rawCompressedSize} final={scenario.result.finalRepairedSize} requested={scenario.result.requestedReduction} rawReduction={scenario.result.rawReduction} finalReduction={scenario.result.finalReduction} />);
    expect(screen.getAllByText("Structural byte reduction")).toHaveLength(3);
    expect(screen.queryByText(/Token reduction/)).not.toBeInTheDocument();
  });

  it("keeps null retention unmeasured and zero relation denominators not applicable", () => {
    expect(retentionLabel({ status: "unmeasured", value: null })).toBe("Unmeasured");
    expect(retentionLabel({ status: "prepared_only", value: null })).toBe("Prepared only");
    expect(coverageLabel({ verified: 0, discovered: 0, mandatory: 0, denominatorMeaning: "relations", sourceNote: "none" })).toBe("Not applicable");
    expect(coveragePercent({ verified: 0, discovered: 0, mandatory: 0, denominatorMeaning: "relations", sourceNote: "none" })).toBe("Not applicable");
  });

  it("renders unmeasured benchmark retention without an empty accuracy chart", () => {
    render(<BenchmarksView benchmark={makeBundle().benchmark} />);
    expect(screen.getByText("Downstream accuracy is unmeasured")).toBeInTheDocument();
    expect(screen.getByText("Prepared only")).toBeInTheDocument();
    expect(screen.getAllByText("Unmeasured").length).toBeGreaterThan(0);
    expect(screen.queryByRole("img", { name: /accuracy/i })).not.toBeInTheDocument();
  });

  it("keeps raw and final reductions separate and shows zero fallback savings", () => {
    const base = makeScenario();
    const fallback = { ...base, result: { ...base.result, status: "verified_fallback" as const, finalAction: "full_fallback" as const, rawReduction: makeMetric(null), finalReduction: makeMetric(0) } };
    expect(isFallbackScenario(fallback)).toBe(true);
    expect(formatReduction(fallback.result.rawReduction)).toBe("Unmeasured");
    expect(formatReduction(fallback.result.finalReduction)).toBe("0.0%");
  });

  it("uses a neutral, non-failing tone for unknown statuses", () => {
    expect(statusTone("future_status")).toBe("neutral");
  });
});
