import { useEffect, useMemo, useState } from "react";
import type { HardwareSnapshot } from "../domain/hardware";
import type { GenerationRequest } from "../domain/generation";
import type { HistoryItem } from "../domain/history";
import { useDreamProvider } from "./providers";
import { GeneratePage } from "./pages/GeneratePage";
import { ModelsPage } from "./pages/ModelsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LabPage } from "./pages/LabPage";
import { MicroscopePage } from "./pages/MicroscopePage";
import { SettingsPage } from "./pages/SettingsPage";
import { SideNav } from "./components/SideNav";
import { TopBar } from "./components/TopBar";
import "./shell.css";

export type Route = "generate" | "models" | "history" | "lab" | "microscope" | "settings";

const navigation: Array<{ id: Route; label: string; icon: string; hint: string }> = [
  { id: "generate", label: "生成", icon: "▧", hint: "使用本地模型创建图像" },
  { id: "models", label: "模型", icon: "◇", hint: "管理本地模型" },
  { id: "history", label: "历史", icon: "◷", hint: "浏览已生成的图像" },
  { id: "lab", label: "实验室", icon: "♧", hint: "进行可控对比实验" },
  { id: "microscope", label: "显微镜", icon: "▥", hint: "检查运行时和模型状态" },
  { id: "settings", label: "设置", icon: "⚙", hint: "配置硬件和应用偏好" },
];

export function App() {
  const provider = useDreamProvider();
  const [route, setRoute] = useState<Route>("generate");
  const [hardware, setHardware] = useState<HardwareSnapshot | null>(null);
  const [hardwareError, setHardwareError] = useState<string | null>(null);
  const [hardwareLoading, setHardwareLoading] = useState(true);
  const [generationPrefill, setGenerationPrefill] = useState<Partial<GenerationRequest> | null>(null);

  useEffect(() => {
    let active = true;
    setHardwareLoading(true);
    setHardwareError(null);
    void provider.getHardware().then((snapshot) => { if (active) setHardware(snapshot); }).catch((reason: unknown) => { if (active) setHardwareError(reason instanceof Error ? reason.message : "Unable to read hardware status"); }).finally(() => { if (active) setHardwareLoading(false); });
    return () => { active = false; };
  }, [provider]);

  const current = useMemo(() => navigation.find((item) => item.id === route) ?? navigation[0], [route]);
  const rerunHistoryItem = (item: HistoryItem) => {
    setGenerationPrefill({ prompt: item.prompt, negativePrompt: item.negativePrompt, modelId: item.modelId, width: item.width, height: item.height, steps: item.steps, cfg: item.cfg, seed: item.seed });
    setRoute("generate");
  };
  const promoteExperiment = (request: Pick<GenerationRequest, "prompt" | "negativePrompt" | "modelId" | "steps" | "cfg" | "seed">) => {
    setGenerationPrefill({ ...request, fusionMode: "none", traceLevel: "basic" });
    setRoute("generate");
  };
  return <div className="dream-app"><TopBar hardware={hardware} loading={hardwareLoading} error={hardwareError} mode={provider.mode} /><div className="workspace-shell"><SideNav items={navigation} active={route} onNavigate={setRoute} /><div className="dream-main"><main className="dream-content" aria-live="polite"><PageHeading title={route === "lab" ? "语义实验室" : current.label} hint={current.hint} /><RoutePage route={route} hardware={hardware} hardwareError={hardwareError} generationPrefill={generationPrefill} onRerun={rerunHistoryItem} onPromoteExperiment={promoteExperiment} /></main></div></div></div>;
}

function PageHeading({ title, hint }: { title: string; hint: string }) {
  return <div className="page-heading"><div><div className="eyebrow">{hint}</div><h1>{title}</h1></div><div className="heading-context"><span className="status-dot" />{title === "生成" ? "可以开始创建" : "本地工作区"}</div></div>;
}

function RoutePage({ route, hardware, hardwareError, generationPrefill, onRerun, onPromoteExperiment }: { route: Route; hardware: HardwareSnapshot | null; hardwareError: string | null; generationPrefill: Partial<GenerationRequest> | null; onRerun: (item: HistoryItem) => void; onPromoteExperiment: (request: Pick<GenerationRequest, "prompt" | "negativePrompt" | "modelId" | "steps" | "cfg" | "seed">) => void }) {
  switch (route) {
    case "generate": return <GeneratePage hardware={hardware} hardwareError={hardwareError} initialRequest={generationPrefill ?? undefined} />;
    case "models": return <ModelsPage />;
    case "history": return <HistoryPage onRerun={onRerun} />;
    case "lab": return <LabPage onPromote={onPromoteExperiment} />;
    case "microscope": return <MicroscopePage />;
    case "settings": return <SettingsPage hardware={hardware} />;
  }
}
