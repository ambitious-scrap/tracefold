import { coverageLabel, hashLabel } from "../contracts/tracefold";
import type { BenchmarkData, DemoScenario } from "../contracts/tracefold";
import { Icon } from "./Icon";

type LandingRoute = "compress" | "architecture" | "benchmarks";

export function LandingView({ benchmark, scenario, onNavigate }: { benchmark?: BenchmarkData; scenario?: DemoScenario; onNavigate: (route: LandingRoute) => void }) {
  const sourceLines = scenario?.source.text.split(/\r?\n/).filter(Boolean).slice(0, 4) ?? ["Loading committed source fixture…"];
  const compactLines = scenario?.compactFragments.slice(0, 4) ?? [];
  const metricValue = (bytes: number | null) => bytes === null ? "Unmeasured" : bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
  const lineage = scenario ? coverageLabel(scenario.certificate.sourceMap) : "—";
  const sourceMapAvailable = scenario?.sourceMap.available === true;
  const certificateStatus = scenario?.certificate.status === "valid" ? "Independent verification passed" : "Verification status pending";
  const sourceHash = scenario ? hashLabel(scenario.certificate.identity.compressedArtifactHash) : "artifact hash loading";
  const lineageNote = sourceMapAvailable ? "Source-map evidence remains inspectable" : "Source map not available in this artifact";

  return <div className="landing-shell">
    <a className="skip-link" href="#landing-content">Skip to content</a>
    <header className="landing-nav" aria-label="TraceFold overview navigation">
      <a className="landing-brand" href="/" aria-label="TraceFold home">
        <span className="landing-brand__mark"><span>T</span><span>F</span></span>
        <span><strong>TraceFold</strong><small>Context compiler</small></span>
      </a>
      <nav className="landing-nav__links" aria-label="Overview sections">
        <a href="#method">Method</a>
        <a href="#trust">Trust boundary</a>
        <a href="#benchmarks">Evidence</a>
      </nav>
      <button className="landing-nav__cta" type="button" onClick={() => onNavigate("compress")}>Open workbench <Icon name="arrow" size={15} /></button>
    </header>

    <main id="landing-content">
      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero__copy">
          <p className="landing-kicker">Context compiler / structural evidence</p>
          <h1 id="landing-title">Make long context <span className="landing-hero__accent">smaller</span> without losing the trail.</h1>
          <p className="landing-hero__lede">TraceFold compiles long context into a smaller, source-mapped representation, then independently verifies protected facts and relations.</p>
          <div className="landing-hero__actions">
            <button className="landing-button landing-button--primary" type="button" onClick={() => onNavigate("compress")}>Try the workbench <Icon name="arrow" size={16} /></button>
            <button className="landing-button landing-button--quiet" type="button" onClick={() => onNavigate("architecture")}>See how it works</button>
          </div>
          <p className="landing-hero__note"><span className="landing-status-dot" aria-hidden="true" />Static demo artifacts · no target-model requests</p>
        </div>

        <div className="landing-instrument" aria-label="TraceFold product preview">
          <div className="landing-instrument__topline"><span>TraceFold / compile request</span><span className="landing-instrument__status"><i />{scenario ? "Verified fixture" : "Loading fixture"}</span></div>
          <div className="landing-instrument__header"><div><span className="landing-instrument__label">Result / {scenario?.fixtureIdentity ?? "committed fixture"}</span><h2>Compact Context v1</h2></div><span className="landing-verified">{certificateStatus}</span></div>
          <div className="landing-instrument__metrics"><div><span>Original</span><strong>{metricValue(scenario?.result.originalSize.bytes ?? null)}</strong></div><div><span>Final artifact</span><strong>{metricValue(scenario?.result.finalRepairedSize.bytes ?? null)}</strong></div><div><span>Lineage</span><strong>{lineage}</strong></div></div>
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
      </section>

      <section className="landing-proof-strip" aria-label="TraceFold principles">
        <div><strong>Source mapped</strong><span>Every compact fragment can point back to recorded evidence.</span></div>
        <div><strong>Verifier separated</strong><span>Structural checks are recomputed outside the compressor.</span></div>
        <div><strong>Claims bounded</strong><span>Answer retention remains unmeasured until inference exists.</span></div>
      </section>

      <section className="landing-section landing-method" id="method" aria-labelledby="method-title">
        <div className="landing-section__intro"><p className="landing-kicker">The method</p><h2 id="method-title">A smaller context with its chain of custody.</h2><p>TraceFold keeps compression, evidence, and evaluation distinct so a useful artifact never becomes an inflated claim.</p></div>
        <div className="landing-method__steps">
          <article><span className="landing-step-mark">01</span><h3>Compile</h3><p>Discover obligations and relations, then compile a compact context from the source.</p><button type="button" onClick={() => onNavigate("compress")}>Open compression <Icon name="arrow" size={14} /></button></article>
          <article><span className="landing-step-mark">02</span><h3>Trace</h3><p>Inspect source spans, mapping types, protected facts, and relation bridges in one workbench.</p><button type="button" onClick={() => onNavigate("architecture")}>View architecture <Icon name="arrow" size={14} /></button></article>
          <article><span className="landing-step-mark">03</span><h3>Verify</h3><p>Recompute structural invariants and record recovery when a compact artifact is not safe.</p><button type="button" onClick={() => onNavigate("benchmarks")}>See evidence <Icon name="arrow" size={14} /></button></article>
        </div>
      </section>

      <section className="landing-boundary" id="trust" aria-labelledby="trust-title">
        <div className="landing-boundary__copy"><p className="landing-kicker">A clear trust boundary</p><h2 id="trust-title">Proof is a separate job.</h2><p>TraceFold does not claim cryptographic proof of semantic equivalence. It produces machine-verifiable structural preservation evidence, then leaves target-model evaluation to a separate benchmark run.</p><button className="landing-button landing-button--light" type="button" onClick={() => onNavigate("architecture")}>Inspect trust domains <Icon name="arrow" size={16} /></button></div>
        <div className="landing-boundary__flow" aria-label="Trust boundary sequence"><BoundaryItem tone="compressor" label="Compressor" value="proposes" /><BoundaryItem tone="certificate" label="Certificate" value="records" /><BoundaryItem tone="verifier" label="Verifier" value="recomputes" /><BoundaryItem tone="recovery" label="Recovery" value="repairs" /></div>
      </section>

      <section className="landing-section landing-evidence" id="benchmarks" aria-labelledby="evidence-title">
        <div className="landing-section__intro"><p className="landing-kicker">Prepared evidence</p><h2 id="evidence-title">Ready for evaluation. Not pretending it happened.</h2><p>ContextProofBench preparation is visible now. Downstream answer retention becomes visible only after live or valid replay inference.</p><button className="landing-button landing-button--primary" type="button" onClick={() => onNavigate("benchmarks")}>View benchmark state <Icon name="arrow" size={16} /></button></div>
        <div className="landing-evidence__facts">
          {benchmark ? <><EvidenceFact value={benchmark.itemCount.toString()} label="prepared questions" /><EvidenceFact value={Object.keys(benchmark.sourceKindDistribution).length.toString()} label="source kinds" /><EvidenceFact value={benchmark.liveRequestCount.toString()} label="live requests" /><EvidenceFact value="Unmeasured" label="downstream retention" /></> : <><EvidenceFact value="—" label="prepared questions" /><EvidenceFact value="—" label="source kinds" /><EvidenceFact value="—" label="live requests" /><EvidenceFact value="Unmeasured" label="downstream retention" /></>}
          <p className="landing-evidence__note">Structural demo data is synthetic. Fixture-byte metrics are not production tokens.</p>
        </div>
      </section>
    </main>

    <footer className="landing-footer"><span>TraceFold · proof workbench</span><span>Structural evidence only · downstream retention unmeasured</span></footer>
  </div>;
}

function BoundaryItem({ tone, label, value }: { tone: string; label: string; value: string }) {
  return <div className={`landing-boundary__item landing-boundary__item--${tone}`}><span className="landing-boundary__dot" /><strong>{label}</strong><span>{value}</span></div>;
}

function EvidenceFact({ value, label }: { value: string; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>;
}
