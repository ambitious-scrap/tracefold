import { useState } from "react";
import type { ArchitectureStage } from "../contracts/tracefold";
import { Icon } from "./Icon";
import { StatusPill } from "./StatusPill";

export function ArchitectureView({ stages }: { stages: ArchitectureStage[] }) {
  const [selectedId, setSelectedId] = useState(stages[0]?.id ?? "");
  const selected = stages.find((stage) => stage.id === selectedId) ?? stages[0];
  return <div className="view view--architecture">
    <header className="view-header"><div><span className="section-kicker">Trust architecture</span><h1>See where responsibility changes.</h1><p>Select a stage to inspect its inputs, outputs, responsibility, and failure behavior.</p></div><div className="architecture-legend"><Legend tone="compressor" label="Compressor" /><Legend tone="verifier" label="Verifier" /><Legend tone="recovery" label="Recovery" /><Legend tone="target_evaluation" label="Target evaluation" /></div></header>
    <section className="pipeline" aria-label="TraceFold pipeline"><div className="pipeline__axis" />{stages.map((stage, index) => <button className={`pipeline-stage pipeline-stage--${stage.trustDomain} ${stage.id === selected?.id ? "is-selected" : ""}`} key={stage.id} type="button" onClick={() => setSelectedId(stage.id)} aria-pressed={stage.id === selected?.id}><span className="pipeline-stage__index">{String(index + 1).padStart(2, "0")}</span><Icon name={stage.trustDomain === "verifier" ? "proof" : stage.trustDomain === "recovery" ? "recovery" : stage.trustDomain === "target_evaluation" ? "benchmarks" : "layers"} size={18} /><strong>{stage.label}</strong>{index < stages.length - 1 ? <span className="pipeline-stage__connector" aria-hidden="true"><Icon name="arrow" size={15} /></span> : null}</button>)}</section>
    {selected ? <section className="stage-inspector" aria-labelledby="stage-title"><div className="stage-inspector__head"><div><span className="section-kicker">Selected stage / {selected.id}</span><h2 id="stage-title">{selected.label}</h2></div><StatusPill tone={selected.trustDomain === "verifier" ? "verified" : selected.trustDomain === "recovery" ? "warning" : "info"}>{selected.trustDomain.replaceAll("_", " ")}</StatusPill></div><div className="stage-flow"><StageBlock label="Input" value={selected.input} /><Icon name="arrow" size={20} /><StageBlock label="Output" value={selected.output} /></div><div className="stage-details"><div><span>Responsibility</span><p>{selected.responsibility}</p></div><div><span>Failure behavior</span><p>{selected.failureBehavior}</p></div></div></section> : null}
    <section className="architecture-boundary"><div><span className="section-kicker">Boundary rule</span><h2>Target evaluation is outside proof.</h2></div><p>The target model receives the final or full context for a separate benchmark run. It does not participate in structural verification, certificate sealing, or recovery decisions.</p></section>
  </div>;
}

function Legend({ tone, label }: { tone: string; label: string }) { return <span className={`legend-tag legend-tag--${tone}`}><i />{label}</span>; }
function StageBlock({ label, value }: { label: string; value: string }) { return <div className="stage-block"><span>{label}</span><code>{value}</code></div>; }
