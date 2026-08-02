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
      <div><span className="section-kicker">Proof workbench / compile request</span><h1>Compress long context. Keep proof.</h1><p>TraceFold compiles long context into a smaller, source-mapped representation and independently verifies protected facts and relations.</p></div>
      <div className="hero-aside"><div className="hero-aside__mark"><span>TF</span><span className="coordinate-dot" /></div><span className="hero-aside__caption">Judge demo / 90 sec</span><span className="hero-aside__note">Structural verification is not downstream accuracy.</span></div>
    </header>
    <div className="demo-banner"><span className="demo-banner__dot" /><strong>{usedStaticFallback || !connected ? "Demo data" : "Backend connected"}</strong><span>{usedStaticFallback || !connected ? "Committed sanitized artifacts · no live model calls" : "POST /v1/compress · response mapped by adapter"}</span></div>
    <section className="control-plane" aria-labelledby="request-title">
      <div className="control-plane__heading"><div><span className="section-kicker">Request</span><h2 id="request-title">Choose what to compile</h2></div><span className="control-plane__step">01 / 03</span></div>
      <form className="request-form" onSubmit={(event) => { event.preventDefault(); onCompress(); }}>
        <label className="field field--kind"><span>Source kind</span><select value={sourceKind} onChange={(event) => onRequestChange({ sourceKind: event.target.value as SourceKind })}>{Object.entries(sourceKindLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
        <label className="field field--fixture"><span>Sample fixture</span><select value={selectedScenarioId} onChange={(event) => onScenarioChange(event.target.value)}>{scenarioOptions.map((item) => <option value={item.id} key={item.id}>{item.shortLabel}</option>)}</select></label>
        <label className="field field--query"><span>Optional query <em>· improves selection only</em></span><input value={request.query ?? ""} onChange={(event) => onRequestChange({ query: event.target.value || null })} placeholder="e.g. ticket=REQ-8842 signed package" /></label>
        <div className="field field--mode"><span>Compression mode</span><div className="segmented-control" role="radiogroup" aria-label="Compression mode">{(["conservative", "target", "aggressive"] as const).map((value) => <button key={value} type="button" role="radio" aria-checked={request.mode === value} className={request.mode === value ? "is-selected" : ""} onClick={() => onRequestChange({ mode: value })}>{value[0].toUpperCase() + value.slice(1)}<small>{value === "conservative" ? "50% target" : value === "target" ? "70% target" : "80% target"}</small></button>)}</div></div>
        <label className="field field--budget"><span>Exact budget <em>· optional</em></span><input type="number" min="1" value={request.exactBudget ?? ""} onChange={(event) => onRequestChange({ exactBudget: event.target.value ? Number(event.target.value) : null })} placeholder="automatic" /></label>
        <label className="field field--tokenizer"><span>Tokenizer identity</span><select value={request.tokenizerIdentity} onChange={(event) => onRequestChange({ tokenizerIdentity: event.target.value })}><option>Fixture byte counter · v1</option><option>Configured tokenizer · not connected</option><option>Provider usage · backend only</option></select></label>
        <label className="field field--attempts"><span>Maximum recovery attempts</span><input type="number" min="1" max="8" value={request.maximumRecoveryAttempts} onChange={(event) => onRequestChange({ maximumRecoveryAttempts: Number(event.target.value) })} /></label>
        <label className="field field--editor"><span>Source editor <em>· exact bytes shown for demo fixture</em></span><textarea value={editorText} onChange={(event) => { setEditorText(event.target.value); onRequestChange({ sourceText: event.target.value }); }} spellCheck={false} aria-label="Source editor" /></label>
        <div className="request-form__action"><span className="request-form__hint"><Icon name="lock" size={14} />Static mode never sends target-model requests.</span><button className="primary-button" type="submit" disabled={busy}>{busy ? <><span className="button-loader" />Compiling evidence</> : <><Icon name="play" size={16} />Compress &amp; verify</>}</button></div>
      </form>
    </section>
    {error ? <div className="error-callout" role="alert"><Icon name="alert" size={17} /><div><strong>{error.code}</strong><p>{error.message}</p><span>Static artifacts remain available from the scenario selector.</span></div></div> : null}
    {scenario ? <>
      <section className="result-header" aria-labelledby="result-title"><div className="result-heading"><div><span className="section-kicker">Result / {scenario.fixtureIdentity}</span><h2 id="result-title">{scenario.label}</h2><p>{scenario.description}</p></div><StatusPill tone={statusTone(scenario.result.status)} label={`Result status: ${scenario.result.status}`}>{scenario.result.status.replaceAll("_", " ")}</StatusPill></div><div className="result-meta"><Meta label="Final action" value={scenario.result.finalAction.replaceAll("_", " ")} /><Meta label="Tokenizer / counter" value={scenario.result.tokenizerIdentity} /><Meta label="Certificate" value={scenario.result.certificateStatus} /><Meta label="Verification" value={scenario.result.verificationStatus} /></div><MetricStrip original={scenario.result.originalSize} raw={scenario.result.rawCompressedSize} final={scenario.result.finalRepairedSize} requested={scenario.result.requestedReduction} rawReduction={scenario.result.rawReduction} finalReduction={scenario.result.finalReduction} /></section>
      <SourceMapWorkbench source={scenario.source} compactContext={scenario.compactContext} fragments={scenario.compactFragments} sourceSpans={scenario.sourceSpans} sourceMapAvailable={scenario.sourceMap.available} />
    </> : <EmptyWorkbench />}
  </div>;
}

function Meta({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function EmptyWorkbench() { return <section className="empty-workbench"><div className="empty-workbench__glyph"><Icon name="compress" size={28} /></div><h2>Load a committed scenario to begin</h2><p>Choose a fixture above. The workbench keeps source, raw candidate, final result, and proof evidence separate.</p></section>; }
