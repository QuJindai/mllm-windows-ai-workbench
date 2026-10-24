import { useEffect, useMemo, useState } from "react";
import type { HardwareSnapshot } from "../domain/hardware";
import { HARDWARE_MAX_AGE_MS, isFreshHardware } from "../domain/hardware";
import type { GenerationRequest } from "../domain/generation";
import type { HistoryItem } from "../domain/history";
import { isIdentityModelId } from "../domain/identity";
import { useDreamProvider } from "./providers";
import { GeneratePage } from "./pages/GeneratePage";
import { IdentityPage } from "./pages/IdentityPage";
import type { IdentityReplay } from "./pages/IdentityPage";
import { ModelsPage } from "./pages/ModelsPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LabPage } from "./pages/LabPage";
import { MicroscopePage } from "./pages/MicroscopePage";
import { SettingsPage } from "./pages/SettingsPage";
import { SideNav } from "./components/SideNav";
import { TopBar } from "./components/TopBar";
import "./shell.css";
import "./workstation.css";
import { useUiPreferences } from "./ui-preferences";

export type Route = "generate" | "identity" | "models" | "history" | "lab" | "microscope" | "settings";

const navigation: Array<{ id: Route; label: string; icon: string; hint: string }> = [
  { id: "generate", label: "生成", icon: "▧", hint: "使用本地模型创建图像" },
  { id: "identity", label: "人物创作", icon: "◉", hint: "参考人物 · 场景创作 · 结果对照" },
  { id: "models", label: "模型", icon: "◇", hint: "管理本地模型" },
  { id: "history", label: "历史", icon: "◷", hint: "浏览已生成的图像" },
  { id: "lab", label: "实验室", icon: "♧", hint: "进行可控对比实验" },
  { id: "microscope", label: "显微镜", icon: "▥", hint: "检查运行时和模型状态" },
  { id: "settings", label: "设置", icon: "⚙", hint: "配置硬件和应用偏好" },
];

export function App() {
  const preferences = useUiPreferences();
  useEffect(() => {
    document.documentElement.dataset.textSize = preferences.textSize;
    document.documentElement.dataset.density = preferences.density;
    document.documentElement.dataset.reduceMotion = String(preferences.reduceMotion);
  }, [preferences]);
  const provider = useDreamProvider();
  const [route, setRoute] = useState<Route>(() => new URLSearchParams(window.location.search).get("view") === "microscope" ? "microscope" : "generate");
  const [hardware, setHardware] = useState<HardwareSnapshot | null>(null);
  const [hardwareError, setHardwareError] = useState<string | null>(null);
  const [hardwareLoading, setHardwareLoading] = useState(true);
  const [generationPrefill, setGenerationPrefill] = useState<Partial<GenerationRequest> | null>(null);
  const [identityReplay, setIdentityReplay] = useState<IdentityReplay | null>(null);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let resumeRequested = false;
    let controller: AbortController | undefined;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let requestTimer: ReturnType<typeof setTimeout> | undefined;
    let staleTimer: ReturnType<typeof setTimeout> | undefined;
    setHardware(null);
    setHardwareLoading(true);
    setHardwareError(null);
    const poll = async () => {
      if (!active || document.hidden || inFlight) return;
      inFlight = true;
      resumeRequested = false;
      const request = new AbortController();
      controller = request;
      requestTimer = setTimeout(() => {
        request.abort();
        if (active && !document.hidden) {
          setHardwareError("硬件采样超时，等待重试");
          setHardwareLoading(false);
        }
      }, 4000);
      try {
        const snapshot = await provider.getHardware(request.signal);
        if (!active || request.signal.aborted) return;
        if (provider.mode === "backend" && !isFreshHardware(snapshot)) throw new Error("硬件采样时间缺失或已过期，请更新后端后重试");
        setHardware(snapshot);
        setHardwareError(null);
        clearTimeout(staleTimer);
        if (provider.mode === "backend") {
          staleTimer = setTimeout(() => {
            if (active) setHardwareError(current => current ?? "硬件采样已过期，等待刷新");
          }, Math.max(0, Date.parse(snapshot.sampledAt!) + HARDWARE_MAX_AGE_MS - Date.now()));
        }
      } catch (reason: unknown) {
        if (active && !request.signal.aborted) setHardwareError(reason instanceof Error ? reason.message : "无法读取硬件状态");
      } finally {
        clearTimeout(requestTimer);
        inFlight = false;
        if (active) {
          setHardwareLoading(false);
          if (!document.hidden) pollTimer = setTimeout(() => { void poll(); }, resumeRequested ? 0 : 3000);
        }
      }
    };
    const visibilityChanged = () => {
      clearTimeout(pollTimer);
      if (document.hidden) {
        clearTimeout(requestTimer);
        clearTimeout(staleTimer);
        controller?.abort();
        setHardwareError("页面隐藏，硬件采样已暂停");
        setHardwareLoading(false);
      } else {
        resumeRequested = true;
        void poll();
      }
    };
    document.addEventListener("visibilitychange", visibilityChanged);
    if (document.hidden) visibilityChanged();
    else void poll();
    return () => {
      active = false;
      controller?.abort();
      clearTimeout(pollTimer);
      clearTimeout(requestTimer);
      clearTimeout(staleTimer);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [provider]);

  const current = useMemo(() => navigation.find((item) => item.id === route) ?? navigation[0], [route]);
  const rerunHistoryItem = (item: HistoryItem) => {
    if (isIdentityModelId(item.modelId)) {
      setIdentityReplay((current) => ({ id: item.id, revision: (current?.revision ?? 0) + 1 }));
      setRoute("identity");
      return;
    }
    setGenerationPrefill({ prompt: item.prompt, negativePrompt: item.negativePrompt, modelId: item.modelId, width: item.width, height: item.height, steps: item.steps, cfg: item.cfg, seed: item.seed });
    setRoute("generate");
  };
  const promoteExperiment = (request: Pick<GenerationRequest, "prompt" | "negativePrompt" | "modelId" | "steps" | "cfg" | "seed">) => {
    setGenerationPrefill({ ...request, fusionMode: "none", traceLevel: "basic" });
    setRoute("generate");
  };
  return <div className="dream-app"><TopBar hardware={hardware} loading={hardwareLoading} error={hardwareError} mode={provider.mode} /><div className="workspace-shell"><SideNav items={navigation} active={route} onNavigate={setRoute} /><div className="dream-main"><main className="dream-content" aria-live="polite"><PageHeading title={route === "lab" ? "语义实验室" : current.label} hint={current.hint} /><RoutePage route={route} hardware={hardware} hardwareError={hardwareError} generationPrefill={generationPrefill} identityReplay={identityReplay} onRerun={rerunHistoryItem} onPromoteExperiment={promoteExperiment} /></main></div></div></div>;
}

function PageHeading({ title, hint }: { title: string; hint: string }) {
  return <div className="page-heading"><div><div className="eyebrow">{hint}</div><h1>{title}</h1></div><div className="heading-context"><span className="status-dot" />{title === "生成" ? "可以开始创建" : "本地工作区"}</div></div>;
}

function RoutePage({ route, hardware, hardwareError, generationPrefill, identityReplay, onRerun, onPromoteExperiment }: { route: Route; hardware: HardwareSnapshot | null; hardwareError: string | null; generationPrefill: Partial<GenerationRequest> | null; identityReplay: IdentityReplay | null; onRerun: (item: HistoryItem) => void; onPromoteExperiment: (request: Pick<GenerationRequest, "prompt" | "negativePrompt" | "modelId" | "steps" | "cfg" | "seed">) => void }) {
  const [identityOpened, setIdentityOpened] = useState(false);
  useEffect(() => { if (route === "identity") setIdentityOpened(true); }, [route]);
  return <>
    <div hidden={route !== "generate"}>
      <GeneratePage hardware={hardware} hardwareError={hardwareError} initialRequest={generationPrefill ?? undefined} />
    </div>
    {(identityOpened || route === "identity") && <div hidden={route !== "identity"}>
      <IdentityPage replay={identityReplay} />
    </div>}
    {route === "models" && <ModelsPage />}
    {route === "history" && <HistoryPage onRerun={onRerun} />}
    {route === "lab" && <LabPage onPromote={onPromoteExperiment} />}
    {route === "microscope" && <MicroscopePage />}
    {route === "settings" && <SettingsPage hardware={hardwareError ? null : hardware} />}
  </>;
}
