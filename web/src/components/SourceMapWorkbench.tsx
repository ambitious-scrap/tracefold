import { useMemo, useState } from "react";
import type { CompactFragment, SourceDocument, SourceSpan } from "../contracts/tracefold";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

interface SourceMapWorkbenchProps {
  source: SourceDocument;
  compactContext: string;
  fragments: CompactFragment[];
  sourceSpans: SourceSpan[];
  sourceMapAvailable?: boolean;
}

export function SourceMapWorkbench({ source, compactContext, fragments, sourceSpans, sourceMapAvailable = false }: SourceMapWorkbenchProps) {
  const [selectedFragmentId, setSelectedFragmentId] = useState<string | null>(fragments[0]?.id ?? null);
  const [query, setQuery] = useState("");
  const [wrap, setWrap] = useState(true);
  const selectedFragment = fragments.find((fragment) => fragment.id === selectedFragmentId) ?? null;
  const selectedSpanIds = useMemo(() => new Set(selectedFragment?.sourceSpanIds ?? []), [selectedFragment]);
  const selectedSourceLines = useMemo(() => {
    const lines = new Set<number>();
    for (const span of sourceSpans) if (selectedSpanIds.has(span.id)) for (let line = span.lineStart; line <= span.lineEnd; line += 1) lines.add(line);
    return lines;
  }, [selectedSpanIds, sourceSpans]);
  const sourceLines = useMemo(() => filterLines(source.text.split("\n"), query), [source.text, query]);
  const compactLines = useMemo(() => filterLines(compactContext.split("\n"), query), [compactContext, query]);

  const selectSourceLine = (line: number) => {
    const candidate = fragments.find((fragment) => fragment.sourceSpanIds.some((spanId) => {
      const span = sourceSpans.find((item) => item.id === spanId);
      return span ? span.lineStart <= line && span.lineEnd >= line : false;
    }));
    if (candidate) setSelectedFragmentId(candidate.id);
  };

  return (
    <section className="source-map" aria-labelledby="comparison-title">
      <div className="source-map__toolbar">
        <div><span className="section-kicker">Source map / bidirectional evidence</span><h2 id="comparison-title">{sourceMapAvailable ? "Select a fragment. Follow its proof." : "Inspect prepared text matches."}</h2></div>
        <div className="source-map__tools">
          <label className="search-field"><Icon name="search" size={15} /><span className="sr-only">Search both contexts</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search evidence" /></label>
          <button className={`text-button ${wrap ? "is-active" : ""}`} type="button" aria-pressed={wrap} onClick={() => setWrap((value) => !value)}>Wrap {wrap ? "on" : "off"}</button>
        </div>
      </div>
      {!sourceMapAvailable ? <div className="source-map__availability" role="status"><Icon name="alert" size={15} /><span><strong>Source-map records unavailable.</strong> Highlighted candidates are text matches from the prepared artifact, not verified lineage.</span></div> : null}
      <div className="source-map__legend" aria-label="Lineage legend">
        <span><i className="legend-swatch legend-swatch--copy" />Exact copy</span>
        <span><i className="legend-swatch legend-swatch--fact" />Compact exact fact</span>
        <span><i className="legend-swatch legend-swatch--relation" />Relation bridge</span>
        <span><i className="legend-swatch legend-swatch--marker" />Synthesized marker</span>
      </div>
      <div className="source-map__columns">
        <ContextPane title="Original context" subline={`${source.label} · ${source.kind}`} lines={sourceLines} wrap={wrap} side="source" selectedLines={selectedSourceLines} onLineSelect={selectSourceLine} />
        <ContextPane title="TraceFold Compact Context v1" subline={`${fragments.length} ${sourceMapAvailable ? "mapped fragments" : "prepared text-match candidates"} · click any fragment`} lines={compactLines} wrap={wrap} side="compact" selectedLines={new Set(selectedFragment ? [selectedFragment.lineStart] : [])} selectedFragmentId={selectedFragmentId} fragments={fragments} onFragmentSelect={setSelectedFragmentId} sourceMapAvailable={sourceMapAvailable} />
      </div>
      <LineageDetail fragment={selectedFragment} sourceSpans={sourceSpans} sourceMapAvailable={sourceMapAvailable} />
    </section>
  );
}

function ContextPane({ title, subline, lines, wrap, side, selectedLines, onLineSelect, selectedFragmentId, fragments = [], onFragmentSelect, sourceMapAvailable = false }: {
  title: string;
  subline: string;
  lines: { value: string; number: number }[];
  wrap: boolean;
  side: "source" | "compact";
  selectedLines: Set<number>;
  onLineSelect?: (line: number) => void;
  selectedFragmentId?: string | null;
  fragments?: CompactFragment[];
  onFragmentSelect?: (id: string) => void;
  sourceMapAvailable?: boolean;
}) {
  return <div className={`context-pane context-pane--${side}`}><header className="context-pane__header"><div><strong>{title}</strong><span>{subline}</span></div><button className="icon-button" type="button" aria-label={`Copy ${title}`} onClick={() => void navigator.clipboard?.writeText(lines.map((line) => line.value).join("\n"))}><Icon name="copy" size={16} /></button></header><div className={`code-viewer ${wrap ? "is-wrapped" : ""}`} role="region" aria-label={title} tabIndex={0}>{lines.length ? lines.map((line) => {
    const fragment = side === "compact" ? fragments.find((candidate) => candidate.lineStart <= line.number && candidate.lineEnd >= line.number) : undefined;
      const selected = selectedLines.has(line.number) || fragment?.id === selectedFragmentId;
    return <button key={`${side}-${line.number}`} className={`code-line ${selected ? "is-selected" : ""} ${fragment ? `code-line--${fragment.outputKind}` : ""}`} type="button" onClick={() => fragment ? onFragmentSelect?.(fragment.id) : onLineSelect?.(line.number)} aria-label={`${title}, line ${line.number}${fragment ? `, ${fragment.outputKind.replaceAll("_", " ")}, ${sourceMapAvailable ? "verified source map" : "prepared text match"}` : ""}`}><span className="line-number" aria-hidden="true">{String(line.number).padStart(3, "0")}</span><code>{line.value || " "}</code>{fragment ? <span className="line-marker" aria-hidden="true">{fragment.mappingType === "many_to_one" ? "M→1" : fragment.mappingType === "one_to_many" ? "1→M" : "="}</span> : null}</button>;
  }) : <p className="code-empty">No matching lines.</p>}</div></div>;
}

function LineageDetail({ fragment, sourceSpans, sourceMapAvailable }: { fragment: CompactFragment | null; sourceSpans: SourceSpan[]; sourceMapAvailable: boolean }) {
  if (!fragment) return <div className="lineage-detail lineage-detail--empty"><Icon name="link" size={17} /><span>Select a compact fragment to inspect source lineage.</span></div>;
  const spans = sourceSpans.filter((span) => fragment.sourceSpanIds.includes(span.id));
  return <aside className="lineage-detail" aria-live="polite"><div className="lineage-detail__lead"><StatusPill tone={fragment.outputKind === "synthesized_marker" || !sourceMapAvailable ? "warning" : "info"}>{sourceMapAvailable ? "source-map record" : "prepared text match"}</StatusPill><strong>{fragment.outputKind.replaceAll("_", " ")}</strong><strong>{fragment.mappingType.replaceAll("_", " ")}</strong></div><div className="lineage-detail__grid"><div><span>Source IDs</span><code>{fragment.sourceIds.join(", ") || "not declared"}</code></div><div><span>Coordinates</span><code>{spans.length ? spans.map((span) => `L${span.lineStart}–${span.lineEnd} · ${span.sourceStart}–${span.sourceEnd}`).join("; ") : "not available"}</code></div><div><span>Obligations</span><code>{fragment.obligationIds.join(", ") || "none"}</code></div><div><span>Relations</span><code>{fragment.relationIds.join(", ") || "none"}</code></div></div><p>{sourceMapAvailable ? fragment.sourceLabels.join(" · ") || "No source lineage declared for this fragment." : "Prepared text-match candidate; complete source-map lineage is not claimed."}</p></aside>;
}

function filterLines(text: string[], query: string): { value: string; number: number }[] {
  const normalized = query.trim().toLowerCase();
  return text.map((value, index) => ({ value, number: index + 1 })).filter((line) => !normalized || line.value.toLowerCase().includes(normalized));
}
