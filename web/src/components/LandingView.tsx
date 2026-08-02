import { coverageLabel, hashLabel } from "../contracts/tracefold";
import type { BenchmarkData, DemoScenario } from "../contracts/tracefold";
import { Icon } from "./Icon";

type LandingRoute = "compress" | "architecture" | "benchmarks";

export function LandingView({ benchmark, scenario, onNavigate }: { benchmark?: BenchmarkData; scenario?: DemoScenario; onNavigate: (route: LandingRoute) => void }) {
  const sourceLines = scenario?.source.text.split(/\r?\n/).filter(Boolean).slice(0, 5) ?? ["Loading committed source fixture…"];
  const compactLines = scenario?.compactFragments.slice(0, 5) ?? [];
  const metricValue = (bytes: number | null) => bytes === null ? "Unmeasured" : bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
  const lineage = scenario ? coverageLabel(scenario.certificate.sourceMap) : "—";
  const sourceMapAvailable = scenario?.sourceMap.available === true;
  const certificateStatus = scenario?.certificate.status === "valid" ? "Independent verification passed" : "Verification status pending";
  const sourceHash = scenario ? hashLabel(scenario.certificate.identity.compressedArtifactHash) : "artifact hash loading";
  const lineageNote = sourceMapAvailable ? "Source-map evidence remains inspectable" : "Source map not available in this artifact";

  return <div className="landing-shell landing-shell--editorial">
    <a className="skip-link" href="#landing-content">Skip to content</a>
    <header className="landing-nav" aria-label="TraceFold overview navigation">
      <a className="landing-brand" href="/" aria-label="TraceFold home">
        <span className="landing-brand__mark" aria-hidden="true"><span>T</span><span>F</span></span>
        <span><strong>TraceFold</strong><small>Context compiler</small></span>
      </a>
      <nav className="landing-nav__links" aria-label="Overview sections">
        <a href="#product">Product</a>
        <a href="#method">Method</a>
        <a href="#trust">Trust boundary</a>
        <a href="#benchmarks">Evidence</a>
      </nav>
      <button className="landing-nav__cta" type="button" onClick={() => onNavigate("compress")}>Open workbench <Icon name="arrow" size={15} /></button>
    </header>

    <main id="landing-content">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero__copy">
          <p className="landing-kicker"><span />Evidence-first context compilation</p>
          <h1 id="landing-title">Compress context.<br /><span>Keep the evidence.</span></h1>
          <p className="landing-hero__lede">TraceFold compiles long context into a smaller, source-mapped representation and independently verifies protected facts and relations.</p>
          <div className="landing-hero__actions">
            <button className="landing-button landing-button--primary" type="button" onClick={() => onNavigate("compress")}>Try the workbench <Icon name="arrow" size={16} /></button>
            <button className="landing-button landing-button--quiet" type="button" onClick={() => onNavigate("architecture")}>Explore the architecture</button>
          </div>
          <div className="landing-hero__assurance" aria-label="Demo assurances">
            <span><i className="landing-status-dot" aria-hidden="true" />Committed demo data</span>
            <span>No target-model requests</span>
            <span>{benchmark?.liveEvidence ? `${benchmark.liveEvidence.pairedRetention.correct}/${benchmark.liveEvidence.pairedRetention.denominator} paired retention` : "Evidence loading"}</span>
          </div>
        </div>
        <div className="landing-hero__trace" aria-hidden="true"><i /><i /><i /></div>
      </section>

      <section className="landing-product-stage" id="product" aria-label="TraceFold product preview">
        <div className="landing-product-stage__halo" aria-hidden="true" />
        <div className="landing-instrument">
          <div className="landing-instrument__chrome">
            <span className="landing-window-dots" aria-hidden="true"><i /><i /><i /></span>
            <span>TraceFold / proof workbench</span>
            <span className="landing-instrument__status"><i />{scenario ? "Verified fixture" : "Loading fixture"}</span>
          </div>
          <div className="landing-instrument__workspace">
            <aside className="landing-instrument__rail" aria-label="Preview navigation">
              <strong>TF</strong>
              <span className="is-active">01 <b>Compress</b></span>
              <span>02 <b>Proof</b></span>
              <span>03 <b>Recovery</b></span>
              <span>04 <b>Benchmarks</b></span>
            </aside>
            <div className="landing-instrument__main">
              <div className="landing-instrument__header">
                <div><span className="landing-instrument__label">Result / {scenario?.fixtureIdentity ?? "committed fixture"}</span><h2>Compact Context <em>v1</em></h2></div>
                <span className="landing-verified"><Icon name="proof" size={14} />{certificateStatus}</span>
              </div>
              <div className="landing-instrument__metrics">
                <div><span>Original</span><strong>{metricValue(scenario?.result.originalSize.bytes ?? null)}</strong></div>
                <div><span>Final artifact</span><strong>{metricValue(scenario?.result.finalRepairedSize.bytes ?? null)}</strong></div>
                <div><span>Source-map coverage</span><strong>{lineage}</strong></div>
              </div>
              <div className="landing-compare-labels" aria-hidden="true"><span>Original evidence</span><span>Source-mapped compact context</span></div>
              <div className="landing-instrument__body">
                <div className="landing-source-lines" aria-label="Original source evidence">
                  {sourceLines.map((line, index) => <span className={sourceMapAvailable && index === 1 ? "is-highlight" : undefined} key={`${line}-${index}`}><b>{String(index + 1).padStart(3, "0")}</b>{line}</span>)}
                </div>
                <div className="landing-compact-lines" aria-label="Compact source-mapped context">
                  {compactLines.length ? compactLines.map((fragment, index) => <span className={sourceMapAvailable && index === 1 ? "is-highlight" : undefined} key={fragment.id}><b>{String(index + 1).padStart(2, "0")}</b>{fragment.text} <em>{fragment.relationIds[0] ?? fragment.outputKind}</em></span>) : <span><b>—</b>Compact artifact loading</span>}
                </div>
              </div>
              <div className="landing-instrument__footer"><span><i className="landing-key landing-key--lineage" />{lineageNote}</span><code>{sourceHash}</code></div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-proof-strip" aria-label="TraceFold principles">
        <div><strong>Source mapped</strong><p>Compact fragments point back to recorded source evidence.</p></div>
        <div><strong>Independently verified</strong><p>Structural checks are recomputed outside the compressor.</p></div>
        <div><strong>Claims stay bounded</strong><p>Phase 9 paired retention is reported with its benchmark, model, and Wilson interval.</p></div>
      </section>

      <section className="landing-section landing-method" id="method" aria-labelledby="method-title">
        <div className="landing-section__intro">
          <p className="landing-kicker">The method</p>
          <h2 id="method-title">A compiler,<br />not a black box.</h2>
          <p>Compression, evidence, and evaluation remain distinct. That makes every result inspectable—and every claim legible.</p>
        </div>
        <div className="landing-method__steps">
          <MethodStep number="01" title="Compile" copy="Discover obligations and relations, then build a smaller context from the source." action="Open compression" onClick={() => onNavigate("compress")} />
          <MethodStep number="02" title="Trace" copy="Follow output fragments back to exact source spans, protected facts, and relation bridges." action="View architecture" onClick={() => onNavigate("architecture")} />
          <MethodStep number="03" title="Verify" copy="Recompute structural invariants and record recovery when an artifact is not safe." action="Inspect evidence" onClick={() => onNavigate("benchmarks")} />
        </div>
      </section>

      <section className="landing-boundary" id="trust" aria-labelledby="trust-title">
        <div className="landing-boundary__copy">
          <p className="landing-kicker">Separated by design</p>
          <h2 id="trust-title">Proof is a separate job.</h2>
          <p>The compressor cannot grade its own work. TraceFold records a certificate candidate, recomputes structural evidence in an independent verifier, and repairs exact spans when required.</p>
          <p className="landing-boundary__disclaimer">Machine-verifiable structural preservation evidence—not cryptographic proof of semantic equivalence.</p>
          <button className="landing-button landing-button--light" type="button" onClick={() => onNavigate("architecture")}>Inspect trust domains <Icon name="arrow" size={16} /></button>
        </div>
        <div className="landing-boundary__flow" aria-label="Trust boundary sequence">
          <BoundaryItem tone="compressor" number="01" label="Compressor" value="proposes" />
          <BoundaryItem tone="certificate" number="02" label="Certificate" value="records" />
          <BoundaryItem tone="verifier" number="03" label="Verifier" value="recomputes" />
          <BoundaryItem tone="recovery" number="04" label="Recovery" value="repairs" />
        </div>
      </section>

      <section className="landing-section landing-evidence" id="benchmarks" aria-labelledby="evidence-title">
        <div className="landing-section__intro">
          <p className="landing-kicker">Frozen Phase 9 evidence</p>
          <h2 id="evidence-title">Measured live.<br />Claimed narrowly.</h2>
          <p>ContextProofBench v1 paired evidence is shown separately from configured context reduction and structural verification.</p>
          <button className="landing-button landing-button--dark" type="button" onClick={() => onNavigate("benchmarks")}>View benchmark evidence <Icon name="arrow" size={16} /></button>
        </div>
        <div className="landing-evidence__facts">
          {benchmark?.liveEvidence ? <><EvidenceFact value={benchmark.itemCount.toString()} label="benchmark items" /><EvidenceFact value={Object.keys(benchmark.sourceKindDistribution).length.toString()} label="source kinds" /><EvidenceFact value={benchmark.liveRequestCount.toString()} label="successful live requests" /><EvidenceFact value={`${benchmark.liveEvidence.pairedRetention.correct}/${benchmark.liveEvidence.pairedRetention.denominator}`} label="paired retention" /></> : <><EvidenceFact value="—" label="benchmark items" /><EvidenceFact value="—" label="source kinds" /><EvidenceFact value="—" label="live requests" /><EvidenceFact value="—" label="paired retention" /></>}
          <p className="landing-evidence__note">Four compressible classes exceeded 70% configured reduction; Python remained incompressible at its protected floor.</p>
        </div>
      </section>

      <section className="landing-final-cta" aria-label="Open TraceFold workbench">
        <p className="landing-kicker">Trace the compression</p>
        <h2>See exactly what stayed,<br />what moved, and why.</h2>
        <button className="landing-button landing-button--primary" type="button" onClick={() => onNavigate("compress")}>Open the proof workbench <Icon name="arrow" size={16} /></button>
      </section>
    </main>

    <footer className="landing-footer"><span>TraceFold · proof workbench</span><span>Structural proof and paired answer evidence remain separate</span></footer>
  </div>;
}

function MethodStep({ number, title, copy, action, onClick }: { number: string; title: string; copy: string; action: string; onClick: () => void }) {
  return <article><span className="landing-step-mark">{number}</span><div><h3>{title}</h3><p>{copy}</p></div><button type="button" onClick={onClick}>{action} <Icon name="arrow" size={14} /></button></article>;
}

function BoundaryItem({ tone, number, label, value }: { tone: string; number: string; label: string; value: string }) {
  return <div className={`landing-boundary__item landing-boundary__item--${tone}`}><span>{number}</span><span className="landing-boundary__dot" /><strong>{label}</strong><span>{value}</span></div>;
}

function EvidenceFact({ value, label }: { value: string; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}
