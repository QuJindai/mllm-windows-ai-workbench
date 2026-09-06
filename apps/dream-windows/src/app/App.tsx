import { useEffect, useMemo, useState } from "react";
import hardwareFixture from "../fixtures/hardware.json";
import type { HardwareSnapshot } from "../domain/hardware";
import { useDreamProvider } from "./providers";
import { GeneratePage } from "./pages/GeneratePage";
import { ModelsPage } from "./pages/ModelsPage";
import { HistoryPage } from "./pages/HistoryPage";
import "./shell.css";

type Route = "generate" | "models" | "history" | "lab" | "microscope" | "settings";

const navigation: Array<{ id: Route; label: string; icon: string; hint: string }> = [
  { id: "generate", label: "Generate", icon: "✦", hint: "Create a local image" },
  { id: "models", label: "Models", icon: "▦", hint: "Inspect installed models" },
  { id: "history", label: "History", icon: "◷", hint: "Browse generated images" },
  { id: "lab", label: "Lab", icon: "⌁", hint: "Run semantic experiments" },
  { id: "microscope", label: "Microscope", icon: "⌕", hint: "Inspect runtime evidence" },
  { id: "settings", label: "Settings", icon: "⚙", hint: "Configure the workstation" },
];

const fallbackHardware = hardwareFixture as HardwareSnapshot;

export function App() {
  const provider = useDreamProvider();
  const [route, setRoute] = useState<Route>("generate");
  const [hardware, setHardware] = useState<HardwareSnapshot>(fallbackHardware);

  useEffect(() => {
    let active = true;
    void provider.getHardware().then((snapshot) => {
      if (active) setHardware(snapshot);
    });
    return () => { active = false; };
  }, [provider]);

  const current = useMemo(() => navigation.find((item) => item.id === route) ?? navigation[0], [route]);

  return (
    <div className="dream-app">
      <SideNav active={route} onNavigate={setRoute} />
      <div className="dream-main">
        <HardwareStatusBar hardware={hardware} providerMode={provider.mode} />
        <main className="dream-content" aria-live="polite">
          <PageHeading eyebrow={current.hint} title={route === "lab" ? "Semantic Lab" : current.label} />
          <RoutePage route={route} />
        </main>
      </div>
    </div>
  );
}

function SideNav({ active, onNavigate }: { active: Route; onNavigate: (route: Route) => void }) {
  return (
    <aside className="side-nav" aria-label="Primary navigation">
      <div className="brand-lockup">
        <div className="brand-mark">D</div>
        <div><div className="brand-name">DREAM</div><div className="brand-caption">LOCAL WORKSTATION</div></div>
      </div>
      <div className="nav-section-label">WORKSPACE</div>
      <nav className="nav-list">
        {navigation.map((item) => (
          <button className={`nav-item ${active === item.id ? "is-active" : ""}`} key={item.id} type="button" aria-current={active === item.id ? "page" : undefined} onClick={() => onNavigate(item.id)}>
            <span className="nav-icon" aria-hidden="true">{item.icon}</span><span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="nav-footer">
        <div className="footer-chip"><span className="status-dot" />Local runtime</div>
        <div className="footer-path">E:\Dream</div><div className="footer-build">GUI Alpha · G0–G3</div>
      </div>
    </aside>
  );
}

function HardwareStatusBar({ hardware, providerMode }: { hardware: HardwareSnapshot; providerMode: "mock" | "backend" }) {
  const ramGb = hardware.ramTotalBytes / 1024 ** 3;
  const vramGb = hardware.vramTotalMiB / 1024;
  return (
    <header className="status-bar">
      <div className="status-title"><span className="pulse-dot" />Hardware Status</div>
      <div className="status-metrics">
        <div className="metric"><span className="metric-label">GPU</span><strong>{hardware.gpuName}</strong></div>
        <div className="metric"><span className="metric-label">VRAM</span><strong>{vramGb.toFixed(1)} GB</strong></div>
        <div className="metric"><span className="metric-label">RAM</span><strong>{ramGb.toFixed(1)} GB</strong></div>
        <div className="metric"><span className="metric-label">CUDA</span><strong className={hardware.cudaReady ? "text-success" : "text-muted"}>{hardware.cudaReady ? "Ready" : "Unavailable"}</strong></div>
      </div>
      <span className={`truth-badge ${providerMode === "mock" ? "truth-demo" : "truth-observed"}`}>{providerMode === "mock" ? "DEMO / MOCK" : "LIVE / BACKEND"}</span>
    </header>
  );
}

function PageHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1></div><div className="heading-context"><span className="status-dot" />Session ready</div></div>;
}

function RoutePage({ route }: { route: Route }) {
  switch (route) {
    case "generate": return <GeneratePage />;
    case "models": return <ModelsPage />;
    case "history": return <HistoryPage />;
    case "lab": return <UnavailablePreview title="Semantic Lab" detail="Research Engine is unavailable in this GUI Alpha." />;
    case "microscope": return <UnavailablePreview title="Microscope" detail="Runtime evidence will appear after a local job completes." />;
    case "settings": return <SettingsPreview />;
  }
}

function GeneratePreview() {
  return <section className="preview-grid"><div className="surface-card hero-card"><div className="card-kicker">LOCAL IMAGE GENERATION</div><h2>Turn a prompt into a traceable result.</h2><p className="muted-copy">The mock provider is connected. Generate controls, progress states, and the result viewer are ready for the next interaction layer.</p><div className="preview-actions"><button className="primary-button" type="button">Generate preview</button><span className="subtle-label">Mock Data · no backend required</span></div></div><div className="surface-card signal-card"><div className="card-head"><span>PIPELINE</span><span className="truth-label truth-derived">DERIVED</span></div><div className="pipeline-row"><span className="pipeline-index">01</span><span>Prompt validation</span><strong>Ready</strong></div><div className="pipeline-row"><span className="pipeline-index">02</span><span>Model reservation</span><strong>Ready</strong></div><div className="pipeline-row"><span className="pipeline-index">03</span><span>CUDA sampling</span><strong>Mocked</strong></div></div></section>;
}

function ModelsPreview() {
  return <section className="preview-grid two-up"><div className="surface-card"><div className="card-head"><span>MODEL REGISTRY</span><span className="truth-label truth-observed">OBSERVED</span></div><h2>Verified models on E:</h2><p className="muted-copy">The model browser will expose architecture, format, checksum, and capability badges from the provider contract.</p><div className="empty-state"><span className="empty-icon">▦</span><span>Loading model cards in the next UI slice.</span></div></div><div className="surface-card inspector-card"><div className="card-kicker">INSPECTOR</div><h3>Selection required</h3><p className="muted-copy">Choose a model to see its file path, memory footprint, and verification record.</p></div></section>;
}

function HistoryPreview() {
  return <section className="preview-grid two-up"><div className="surface-card"><div className="card-head"><span>HISTORY GRID</span><span className="truth-label truth-demo">MOCK DATA</span></div><h2>Your local generation trail.</h2><p className="muted-copy">Browse results as a continuous collection. Selecting a card will open the full viewer with neighboring context.</p><div className="empty-state"><span className="empty-icon">◷</span><span>History carousel will be connected in the next UI slice.</span></div></div><div className="surface-card inspector-card"><div className="card-kicker">VIEWER</div><h3>Nothing selected</h3><p className="muted-copy">The inspector preserves context while you move through adjacent results.</p></div></section>;
}

function UnavailablePreview({ title, detail }: { title: string; detail: string }) {
  return <section className="surface-card unavailable-card"><div className="unavailable-symbol">—</div><h2>{title}</h2><p className="muted-copy">{detail}</p><span className="truth-label truth-unavailable">UNAVAILABLE</span></section>;
}

function SettingsPreview() {
  return <section className="preview-grid two-up"><div className="surface-card"><div className="card-kicker">WORKSTATION</div><h2>Settings</h2><p className="muted-copy">Dream assets, cache, and provider selection are pinned to the E: drive policy.</p><div className="path-row"><span>Dream root</span><code>E:\Dream</code></div></div><div className="surface-card"><div className="card-kicker">DISPLAY</div><h3>DPI-aware layout</h3><p className="muted-copy">The shell uses flexible sizing and remains usable at 100%, 125%, and 150% Windows scaling.</p></div></section>;
}
