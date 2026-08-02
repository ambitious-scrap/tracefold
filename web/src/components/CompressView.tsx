import { useEffect, useMemo, useState } from "react";
import type { CompressRequest, DemoBundle, DemoScenario, SourceKind } from "../contracts/tracefold";
import { sourceKindLabels } from "../contracts/tracefold";
import { Icon } from "./Icon";
import { MetricStrip } from "./MetricStrip";
import { SourceMapWorkbench } from "./SourceMapWorkbench";
import { StatusPill } from "./StatusPill";
import { statusTone } from "./statusTone";

export function CompressView({
  bundle,
  scenario,
  selectedScenarioId,
  request,
  busy,
  connected,
  usedStaticFallback,
  error,
  onRequestChange,
  onScenarioChange,
  onCompress,
}: {
  bundle: DemoBundle;
  scenario: DemoScenario | null;
  selectedScenarioId: string;
  request: CompressRequest;
  busy: boolean;
  connected: boolean;
  usedStaticFallback: boolean;
  error: { code: string; message: string } | null;
  onRequestChange: (patch: Partial<CompressRequest>) => void;
  onScenarioChange: (id: string) => void;
  onCompress: () => void;
}) {
  const [editorText, setEditorText] = useState(request.sourceText);
  const sourceKind = request.sourceKind;
  useEffect(() => setEditorText(request.sourceText), [request.sourceText]);
  const scenarioOptions = useMemo(() => bundle.scenarios.filter((item) => item.id !== "prepared-benchmark"), [bundle.scenarios]);

  return <div className="view view--compress">
    <header className="view-header view-header--hero">
      <div><span className="section-kicker">Compression workbench</span><h1>Compress context. Verify what remains.</h1><p>Create a smaller context, then inspect preserved facts, relations, and source evidence.</p></div>
    </header>
    <div className="demo-banner"><span className="demo-banner__dot" /><strong>{usedStaticFallback ? "Demo fallback" : !connected ? "Static demo" : "Backend connected"}</strong><span>{usedStaticFallback ? "Committed scenario; not generated from custom input" : !connected ? "Committed sanitized artifacts · no live model calls" : "POST /v1/compress · response mapped by adapter"}</span></div>
    <section className="control-plane" aria-labelledby="request-title">
      <div className="control-plane__heading"><h2 id="request-title">Compression request</h2></div>
      <form className="request-form" onSubmit={(event) => { event.preventDefault(); onCompress(); }}>
        <label className="field field--kind"><span>Source kind</span><select value={sourceKind} onChange={(event) => onRequestChange({ sourceKind: event.target.value as SourceKind })}>{Object.entries(sourceKindLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="field field--fixture"><span>Demo scenario</span><select value={selectedScenarioId} onChange={(event) => onScenarioChange(event.target.value)}>{scenarioOptions.map((item) => <option value={item.id} key={item.id}>{item.shortLabel}</option>)}</select></label>
        <label className="field field--query"><span>Query <em>· optional; guides context selection</em></span><input value={request.query ?? ""} onChange={(event) => onRequestChange({ query: event.target.value || null })} placeholder="Example: ticket REQ-8842 signed package" /></label>
        <div className="field field--mode"><span>Compression mode</span><div className="segmented-control" role="radiogroup" aria-label="Compression mode">{(["conservative", "target", "aggressive"] as const).map((value) => <button key={value} type="button" role="radio" aria-checked={request.mode === value} className={request.mode === value ? "is-selected" : ""} onClick={() => onRequestChange({ mode: value })}>{value[0].toUpperCase() + value.slice(1)}<small>{value === "conservative" ? "50% target" : value === "target" ? "70% target" : "80% target"}</small></button>)}</div></div>
        <label className="field field--budget"><span>Exact budget <em>· optional</em></span><input type="number" min="1" value={request.exactBudget ?? ""} onChange={(event) => onRequestChange({ exactBudget: event.target.value ? Number(event.target.value) : null })} placeholder="Automatic" /></label>
        <label className="field field--tokenizer"><span>Tokenizer backend</span><select value={request.tokenizerBackend} onChange={(event) => onRequestChange({ tokenizerBackend: event.target.value })}><option value="tiktoken">tiktoken</option><option value="fixture-only">fixture-only</option></select></label>
        <label className="field field--tokenizer"><span>Tokenizer encoding</span><input value={request.tokenizerEncoding} onChange={(event) => onRequestChange({ tokenizerEncoding: event.target.value })} /></label>
        <label className="field field--attempts"><span>Recovery attempt limit</span><input type="number" min="1" max="8" value={request.maximumRecoveryAttempts} onChange={(event) => onRequestChange({ maximumRecoveryAttempts: Number(event.target.value) })} /></label>
        <label className="field field--budget"><span>Maximum final budget <em>· optional</em></span><input type="number" min="1" value={request.maximumFinalBudget ?? ""} onChange={(event) => onRequestChange({ maximumFinalBudget: event.target.value ? Number(event.target.value) : null })} placeholder="Automatic" /></label>
        <label className="field field--editor"><span>Source context</span><textarea value={editorText} onChange={(event) => { setEditorText(event.target.value); onRequestChange({ sourceText: event.target.value }); }} spellCheck={false} aria-label="Source context" /></label>
        <div className="request-form__action"><span className="request-form__hint"><Icon name="lock" size={14} />No target-model request.</span><button className="primary-button" type="submit" disabled={busy}>{busy ? <><span className="button-loader" />Compressing and verifying</> : <><Icon name="play" size={16} />Compress &amp; verify</>}</button></div>
      </form>
    </section>
    {error ? <div className="error-callout" role="alert"><Icon name="alert" size={17} /><div><strong>Compression service unavailable</strong><p>{error.message}</p><span>Choose another committed scenario or try again.</span><code>{error.code}</code></div></div> : null}
    {scenario ? <>
      <section className="result-header" aria-labelledby="result-title"><div className="result-heading"><div><span className="result-context">{scenario.fixtureIdentity}</span><h2 id="result-title">{scenario.label}</h2><p>{scenario.description}</p></div><StatusPill tone={statusTone(scenario.result.status)} label={`Result status: ${scenario.result.status}`}>{scenario.result.status.replaceAll("_", " ")}</StatusPill></div><div className="result-meta"><Meta label="Final action" value={scenario.result.finalAction.replaceAll("_", " ")} /><Meta label="Measurement source" value={scenario.result.tokenizerIdentity} /><Meta label="Certificate" value={scenario.result.certificateStatus} /><Meta label="Verification" value={scenario.result.verificationStatus} /></div>{scenario.runtimeSourceMapSummary ? <div className="source-map__availability" role="status"><Icon name="alert" size={15} /><span><strong>Source-map summary available.</strong> Detailed span mappings are not included in the public response. Map {scenario.runtimeSourceMapSummary.mapId ?? "not emitted"}; {scenario.runtimeSourceMapSummary.artifactCount} artifacts, {scenario.runtimeSourceMapSummary.spanCount} spans, {scenario.runtimeSourceMapSummary.mappingCount} mappings, {scenario.runtimeSourceMapSummary.omissionCount} omissions. Recovery: {scenario.runtimeRecoverySummary?.attemptCount ?? 0} attempts, {scenario.runtimeRecoverySummary?.restoredTokenCount ?? 0} restored tokens.</span></div> : null}<MetricStrip original={scenario.result.originalSize} raw={scenario.result.rawCompressedSize} final={scenario.result.finalRepairedSize} requested={scenario.result.requestedReduction} rawReduction={scenario.result.rawReduction} finalReduction={scenario.result.finalReduction} /></section>
      <SourceMapWorkbench source={scenario.source} compactContext={scenario.compactContext} fragments={scenario.compactFragments} sourceSpans={scenario.sourceSpans} sourceMapAvailable={scenario.sourceMap.available} unavailableNote={scenario.sourceMap.note} />
    </> : <EmptyWorkbench />}
  </div>;
}

function Meta({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function EmptyWorkbench() { return <section className="empty-workbench"><div className="empty-workbench__glyph"><Icon name="compress" size={28} /></div><h2>Choose a demo scenario</h2><p>Select a committed fixture to compare its source, compact context, and verification evidence.</p></section>; }
