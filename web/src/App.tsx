import { useCallback, useEffect, useMemo, useState } from "react";
import type { DemoBundle, DemoScenario, CompressRequest, ScenarioId } from "./contracts/tracefold";
import { createTracefoldClient, type ClientMode } from "./api/tracefoldClient";
import { ArchitectureView } from "./components/ArchitectureView";
import { BenchmarksView } from "./components/BenchmarksView";
import { CompressView } from "./components/CompressView";
import { Icon, type IconName } from "./components/Icon";
import { ProofView } from "./components/ProofView";
import { RecoveryView } from "./components/RecoveryView";

type Route = "compress" | "proof" | "recovery" | "benchmarks" | "architecture";
type LoadState = "loading" | "ready" | "error";

const navItems: { route: Route; label: string; note: string; icon: IconName }[] = [
  { route: "compress", label: "Compress", note: "Source → compact", icon: "compress" },
  { route: "proof", label: "Proof", note: "Invariants & lineage", icon: "proof" },
  { route: "recovery", label: "Recovery", note: "Restore & reverify", icon: "recovery" },
  { route: "benchmarks", label: "Benchmarks", note: "Prepared evidence", icon: "benchmarks" },
  { route: "architecture", label: "Architecture", note: "Trust boundaries", icon: "architecture" },
];

const guideScenes: { route: Route; scenario: ScenarioId; label: string }[] = [
  { route: "compress", scenario: "verified-target", label: "Select long enterprise context" },
  { route: "compress", scenario: "verified-target", label: "Run Target compression" },
  { route: "compress", scenario: "verified-target", label: "Reveal Compact Context v1" },
  { route: "proof", scenario: "verified-target", label: "Inspect relation evidence" },
  { route: "recovery", scenario: "recovery-fallback", label: "Run recovery fixture" },
  { route: "recovery", scenario: "recovery-fallback", label: "Show final verified result" },
  { route: "benchmarks", scenario: "prepared-benchmark", label: "Show honest benchmark state" },
];

export function App() {
  const client = useMemo(() => createTracefoldClient(), []);
  const [route, setRoute] = useState<Route>(() => routeFromPath(window.location.pathname));
  const [bundle, setBundle] = useState<DemoBundle | null>(null);
  const [scenario, setScenario] = useState<DemoScenario | null>(null);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("verified-target");
  const [request, setRequest] = useState<CompressRequest>({ sourceKind: "document", sourceText: "", query: null, mode: "target", exactBudget: null, tokenizerIdentity: "Fixture byte counter · v1", maximumRecoveryAttempts: 3, fixtureId: "verified-target" });
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [usedStaticFallback, setUsedStaticFallback] = useState(client.mode === "static");
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [guidedStep, setGuidedStep] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const nextBundle = await client.loadDemoData();
      setBundle(nextBundle);
      const initial = nextBundle.scenarios.find((item) => item.id === "verified-target") ?? nextBundle.scenarios[0];
      setScenario(initial);
      setSelectedScenarioId(initial.id);
      setRequest((current) => ({ ...current, sourceKind: initial.source.kind, sourceText: initial.source.text, fixtureId: initial.id }));
      setLoadState("ready");
    } catch (cause) {
      setLoadState("error");
      setLoadError(cause instanceof Error ? cause.message : "Demo data could not be loaded.");
    }
  }, [client]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const onPopState = () => setRoute(routeFromPath(window.location.pathname));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((next: Route) => {
    window.history.pushState({}, "", `/${next}`);
    setRoute(next);
    setGuidedStep(null);
  }, []);

  const chooseScenario = useCallback((id: string) => {
    if (!bundle) return;
    const next = bundle.scenarios.find((item) => item.id === id);
    if (!next) return;
    setScenario(next);
    setSelectedScenarioId(next.id);
    setRequest((current) => ({ ...current, sourceKind: next.source.kind, sourceText: next.source.text, fixtureId: next.id, mode: next.mode }));
    setError(null);
  }, [bundle]);

  const runCompression = useCallback(async () => {
    setBusy(true);
    setError(null);
    const response = await client.compress(request);
    if (response.scenario) {
      setScenario(response.scenario);
      setSelectedScenarioId(response.scenario.id);
      setConnected(response.connected);
      setUsedStaticFallback(response.usedStaticFallback);
      setError(response.error ? { code: response.error.code, message: `${response.error.message} Showing committed demo data instead.` } : null);
    } else if (bundle) {
      const fallback = bundle.scenarios.find((item) => item.id === selectedScenarioId) ?? bundle.scenarios[0];
      setScenario(fallback);
      setUsedStaticFallback(true);
      setError({ code: response.error?.code ?? "BACKEND_UNAVAILABLE", message: response.error ? `${response.error.message} Showing committed demo data instead.` : "Backend unavailable. Showing committed demo data instead." });
    }
    setBusy(false);
  }, [bundle, client, request, selectedScenarioId]);

  const startGuide = () => {
    setGuidedStep(0);
    chooseScenario("verified-target");
    navigate("compress");
  };

  const nextGuide = () => {
    if (guidedStep === null) return;
    const nextStep = guidedStep + 1;
    if (nextStep >= guideScenes.length) { setGuidedStep(null); return; }
    const scene = guideScenes[nextStep];
    chooseScenario(scene.scenario);
    navigate(scene.route);
    setGuidedStep(nextStep);
  };

  if (loadState === "loading") return <LoadingShell />;
  if (loadState === "error" || !bundle || !scenario) return <ErrorShell message={loadError ?? "No committed demo bundle found."} retry={() => void load()} />;

  const currentScenario = route === "recovery" && scenario.recovery === null
    ? bundle.scenarios.find((item) => item.id === "recovery-fallback") ?? scenario
    : scenario;
  const mode: ClientMode = client.mode;

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <aside className="side-rail" aria-label="Primary navigation"><div className="brand-lockup"><div className="brand-mark"><span>T</span><span>F</span></div><div><strong>TraceFold</strong><span>Proof workbench</span></div></div><div className="rail-rule" /><nav><span className="rail-label">Navigation</span>{navItems.map((item) => <button className={`nav-item ${route === item.route ? "is-active" : ""}`} type="button" key={item.route} onClick={() => navigate(item.route)} aria-current={route === item.route ? "page" : undefined}><Icon name={item.icon} size={19} /><span><strong>{item.label}</strong><small>{item.note}</small></span></button>)}</nav><div className="rail-footer"><span className="rail-label">Session</span><code>STATIC / V1</code><span className="rail-footnote">No target-model requests in demo mode.</span></div></aside>
    <main id="main-content" className="main-shell"><div className="topbar"><div className="topbar__context"><span className="coordinate-cross" aria-hidden="true">+</span><span>TraceFold / {route}</span></div><div className="topbar__actions"><span className={`connection-state ${connected ? "is-connected" : ""}`}><i />{connected ? "Backend connected" : mode === "backend" ? "Backend unavailable" : "Static demo"}</span><button className="guide-button" type="button" onClick={guidedStep === null ? startGuide : nextGuide}><Icon name={guidedStep === null ? "play" : "arrow"} size={15} />{guidedStep === null ? "Start guided demo" : `Next scene · ${guidedStep + 1}/7`}</button></div></div>{guidedStep !== null ? <div className="guide-strip" role="status"><span>Guided demo / Scene {guidedStep + 1}</span><strong>{guideScenes[guidedStep].label}</strong><span>Separate labelled fixtures keep evidence honest.</span></div> : null}
      {route === "compress" ? <CompressView bundle={bundle} scenario={scenario} selectedScenarioId={selectedScenarioId} request={request} busy={busy} connected={connected} usedStaticFallback={usedStaticFallback} error={error} onRequestChange={(patch) => setRequest((current) => ({ ...current, ...patch }))} onScenarioChange={chooseScenario} onCompress={() => void runCompression()} /> : null}
      {route === "proof" ? <ProofView scenario={currentScenario} /> : null}
      {route === "recovery" ? <RecoveryView scenario={currentScenario} /> : null}
      {route === "benchmarks" ? <BenchmarksView benchmark={bundle.benchmark} /> : null}
      {route === "architecture" ? <ArchitectureView stages={bundle.architecture} /> : null}
      <footer className="app-footer"><span>TraceFold · static demo artifacts</span><span>Structural evidence only · downstream retention unmeasured</span></footer>
    </main>
  </div>;
}

function routeFromPath(path: string): Route { const name = path.replace(/^\//, "").split("/")[0] as Route; return navItems.some((item) => item.route === name) ? name : "compress"; }

function LoadingShell() { return <div className="shell-message"><div className="loading-orbit"><span /></div><h1>Loading committed proof artifacts</h1><p>Reading sanitized demo data. No backend request is made.</p></div>; }
function ErrorShell({ message, retry }: { message: string; retry: () => void }) { return <div className="shell-message shell-message--error"><Icon name="alert" size={26} /><h1>Demo data unavailable</h1><p>{message}</p><button className="primary-button" type="button" onClick={retry}>Try loading again</button></div>; }
