import type { HardwareSnapshot } from "../../domain/hardware";
import { TruthBadge } from "./TruthBadge";

function shortGpuName(name?: string) {
  if (!name) return "GPU 不可用";
  const match = name.match(/RTX\s+\d+\s+Ada/i);
  return match ? `${match[0]} 6GB` : name;
}

function gb(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(0)} GB`;
}

export function TopBar({ hardware, loading, error, mode }: { hardware: HardwareSnapshot | null; loading: boolean; error: string | null; mode: "mock" | "backend" }) {
  return (
    <header className="top-bar">
      <span className="sr-only">硬件状态</span>
      <div className="top-brand">
        <div className="brand-mark" aria-hidden="true">D</div>
        <div><div className="top-brand-name">Dream</div><div className="top-brand-links"><span>创作</span><span>探索</span><span>理解</span></div></div>
      </div>
      <div className="top-metrics">
        <div className="top-metric"><span className="top-metric-icon">GPU</span><span><strong>{shortGpuName(hardware?.gpuName)}</strong><small>{hardware ? `${hardware.gpuUtil}%` : "—"}</small></span><i className="mini-meter gpu-meter" /></div>
        <div className="top-metric"><span className="top-metric-icon">RAM</span><span><strong>RAM {hardware ? gb(hardware.ramTotalBytes) : "—"}</strong><small>{hardware ? `${Math.round((hardware.ramUsedBytes / hardware.ramTotalBytes) * 100)}%` : "—"}</small></span><i className="mini-meter ram-meter" /></div>
        <div className="top-ready"><span className="status-dot" />{loading ? "正在检测硬件" : hardware?.cudaReady ? "CUDA 就绪" : "CUDA 不可用"}</div>
      </div>
      <div className="top-context"><span className="folder-icon">⌂</span><span>{hardware?.dreamRoot ?? "E:\\Dream"}</span></div>
      <div className="top-tagline">本地 AI · 更深的想象</div>
      <TruthBadge truth={error ? "unavailable" : mode === "mock" ? "demo" : "observed"} label={error ? "硬件错误" : mode === "mock" ? "演示 / 模拟" : "实时 / 后端"} />
    </header>
  );
}
