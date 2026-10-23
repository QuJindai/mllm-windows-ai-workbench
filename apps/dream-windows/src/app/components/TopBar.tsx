import type { HardwareSnapshot } from "../../domain/hardware";
import { isFreshHardware } from "../../domain/hardware";
import { TruthBadge } from "./TruthBadge";

function shortGpuName(name?: string, totalMiB?: number) {
  if (!name) return "GPU 不可用";
  const match = name.match(/RTX\s+\d+\s+Ada/i);
  return match ? `${match[0]}${totalMiB ? ` ${Math.round(totalMiB / 1024)}GB` : ""}` : name;
}

function gb(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(0)} GB`;
}

export function TopBar({ hardware, loading, error, mode }: { hardware: HardwareSnapshot | null; loading: boolean; error: string | null; mode: "mock" | "backend" }) {
  const demo = mode === "mock" || hardware?.isMock;
  const available = !error && !loading && hardware && (demo || (hardware.truth === "observed" && isFreshHardware(hardware)));
  const percent = (value: number | undefined) => value != null && Number.isFinite(value) && value >= 0 && value <= 100 ? value : undefined;
  const gpuUtil = available ? percent(hardware.gpuUtil) : undefined;
  const ramUtil = available && hardware.ramTotalBytes > 0 ? percent(Math.round(hardware.ramUsedBytes / hardware.ramTotalBytes * 100)) : undefined;
  const sampleTime = hardware?.sampledAt && Number.isFinite(Date.parse(hardware.sampledAt)) ? hardware.sampledAt : undefined;
  const vram = available && Number.isFinite(hardware.vramUsedMiB) && hardware.vramUsedMiB >= 0 && hardware.vramUsedMiB <= hardware.vramTotalMiB && hardware.vramTotalMiB > 0
    ? `${hardware.vramUsedMiB} / ${hardware.vramTotalMiB} MiB` : "不可用";
  return (
    <header className="top-bar">
      <span className="sr-only">硬件状态</span>
      <div className="top-brand">
        <div className="brand-mark" aria-hidden="true">D</div>
        <div><div className="top-brand-name">Dream</div><div className="top-brand-links"><span>创作</span><span>探索</span><span>理解</span></div></div>
      </div>
      <div className="top-metrics">
        <div className="top-metric"><span className="top-metric-icon">GPU</span><span><strong>{shortGpuName(hardware?.gpuName, hardware?.vramTotalMiB)}</strong><small>{gpuUtil == null ? "不可用" : `${gpuUtil}%`}</small><small className="top-vram">显存 {vram}</small></span><ResourceMeter label="GPU 使用率" value={gpuUtil} className="gpu-meter" /></div>
        <div className="top-metric"><span className="top-metric-icon">RAM</span><span><strong>RAM {available && hardware.ramTotalBytes > 0 ? gb(hardware.ramTotalBytes) : "—"}</strong><small>{ramUtil == null ? "不可用" : `${ramUtil}%`}</small></span><ResourceMeter label="RAM 使用率" value={ramUtil} className="ram-meter" /></div>
        <div className="top-hardware-status" title={error ?? "前台每 3 秒采样；后台暂停"}><div className="top-ready"><span className={`status-dot ${available && hardware.cudaReady ? "" : "status-unknown"}`} />{loading ? "正在检测硬件" : !available ? "硬件不可用" : hardware.cudaReady ? "CUDA 就绪" : "CUDA 不可用"}</div><small className="top-sample-time">{sampleTime ? <>{available ? "采样" : "上次采样"} <time dateTime={sampleTime} title={sampleTime}>{new Date(sampleTime).toLocaleTimeString("zh-CN", { hour12: false })}</time></> : "尚无采样时间"}</small></div>
      </div>
      <div className="top-context"><span className="folder-icon">⌂</span><span>{hardware?.dreamRoot ?? "E:\\Dream"}</span></div>
      <div className="top-tagline">本地 AI · 更深的想象</div>
      <TruthBadge truth={!available ? "unavailable" : demo ? "demo" : "observed"} label={!available ? (loading ? "等待采样" : "采样不可用") : demo ? "演示 / 模拟" : "采样 / 后端"} />
    </header>
  );
}

function ResourceMeter({ label, value, className }: { label: string; value?: number; className: string }) {
  return <span className={`mini-meter ${className}`} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={value} aria-valuetext={value == null ? "不可用" : `${value}%`}>
    {value != null && <span style={{ width: `${value}%` }} />}
  </span>;
}
