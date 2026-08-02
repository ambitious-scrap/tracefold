import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SourceMapWorkbench } from "../components/SourceMapWorkbench";
import { fragment, source, sourceSpan } from "./factories";

describe("source-map workbench", () => {
  it("highlights compact-to-source lineage and source-to-compact lineage", () => {
    const secondSpan = { ...sourceSpan, id: "span:test:policy", lineStart: 1, lineEnd: 1, sourceStart: 0, sourceEnd: 6, text: "Policy" };
    const secondFragment = { ...fragment, id: "fragment:test:policy", text: "approval=required", sourceSpanIds: [secondSpan.id], lineStart: 2, lineEnd: 2, outputKind: "compact_exact_relation" as const, mappingType: "many_to_one" as const };
    render(<SourceMapWorkbench source={source} compactContext={`${fragment.text}\n${secondFragment.text}`} fragments={[fragment, secondFragment]} sourceSpans={[sourceSpan, secondSpan]} sourceMapAvailable />);

    const originalLineTwo = screen.getByRole("button", { name: /Original context, line 2/ });
    const compactLineOne = screen.getByRole("button", { name: /TraceFold Compact Context v1, line 1/ });
    expect(compactLineOne).toHaveClass("is-selected");
    expect(originalLineTwo).toHaveClass("is-selected");

    const originalLineOne = screen.getByRole("button", { name: /Original context, line 1/ });
    fireEvent.click(originalLineOne);
    const compactLineTwo = screen.getByRole("button", { name: /TraceFold Compact Context v1, line 2/ });
    expect(compactLineTwo).toHaveClass("is-selected");
    expect(screen.getByText("compact exact relation")).toBeInTheDocument();
    expect(screen.getByText("many to one")).toBeInTheDocument();
  });

  it("labels synthesized markers without implying exact source lineage", () => {
    const synthesized = { ...fragment, id: "fragment:test:marker", text: "[omitted: review evidence]", sourceSpanIds: [], sourceIds: [], outputKind: "synthesized_marker" as const, exactness: "semantic_lineage_only" as const, obligationIds: [], relationIds: [], sourceLabels: [] };
    render(<SourceMapWorkbench source={source} compactContext={synthesized.text} fragments={[synthesized]} sourceSpans={[sourceSpan]} />);
    expect(screen.getByText(/Detailed lineage unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /synthesized marker/ })).toBeInTheDocument();
    expect(screen.getByText("synthesized marker")).toBeInTheDocument();
    expect(screen.getByText("not declared")).toBeInTheDocument();
  });

  it("survives search filtering and very long source lines", () => {
    const longSource = { ...source, text: `${"x".repeat(5000)}\nprotected` };
    render(<SourceMapWorkbench source={longSource} compactContext="protected" fragments={[]} sourceSpans={[]} />);
    fireEvent.change(screen.getByPlaceholderText("Search evidence"), { target: { value: "protected" } });
    expect(screen.getAllByText("protected").length).toBe(2);
    expect(screen.queryByText("No matching lines.")).not.toBeInTheDocument();
  });
});
