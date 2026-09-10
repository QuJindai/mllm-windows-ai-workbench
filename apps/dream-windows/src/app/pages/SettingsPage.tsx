import { useEffect, useState } from "react";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { DreamSettings, WorkspaceEntry } from "../../domain/settings";
import { useDreamProvider } from "../providers";
import { TruthBadge } from "../components/TruthBadge";

const defaults: DreamSettings = {
  dreamRoot: "E:\\Dream",
  modelsPath: "E:\\Dream\\models",
  outputsPath: "E:\\Dream\\outputs",
  historyPath: "E:\\Dream\\history",
  cachePath: "E:\\Dream\\cache",
  logsPath: "E:\\Dream\\logs",
  autopilotEnabled: true,
  precisionMode: "fp16",
  fallbackToCpu: true,
  tileMode: "automatic",
  vaeMemoryMode: "sliced",
  attentionSlicing: true,
  vramThresholdGb: 4,
  optimizationLevel: "balanced",
};

type SettingsTab = "hardware" | "inference" | "interface" | "advanced" | "about";

const tabs: Array<{ id: SettingsTab; label: string }> = [
  { id: "hardware", label: "硬件" },
  { id: "inference", label: "模型与推理" },
  { id: "interface", label: "用户界面" },
  { id: "advanced", label: "高级" },
  { id: "about", label: "关于" },
];

const pathEntries: Array<{ label: string; key: WorkspaceEntry; setting: keyof DreamSettings }> = [
  { label: "基础目录", key: "base", setting: "dreamRoot" },
  { label: "模型", key: "models", setting: "modelsPath" },
  { label: "输出", key: "outputs", setting: "outputsPath" },
  { label: "历史", key: "history", setting: "historyPath" },
  { label: "缓存", key: "cache", setting: "cachePath" },
  { label: "日志", key: "logs", setting: "logsPath" },
];

export function SettingsPage({ hardware }: { hardware: HardwareSnapshot | null }) {
  const provider = useDreamProvider();
  const [settings, setSettings] = useState<DreamSettings>(defaults);
  const [activeTab, setActiveTab] = useState<SettingsTab>("hardware");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [workingAction, setWorkingAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void provider.getSettings().then((value) => {
      if (active) setSettings(value);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "无法加载设置");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [provider]);

  const update = async (changes: Partial<DreamSettings>) => {
    setSaving(true);
    try {
      const value = await provider.updateSettings(changes);
      setSettings(value);
      setNotice("设置已保存到 E:\\Dream 工作区");
      setError(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "无法保存设置");
    } finally {
      setSaving(false);
    }
  };

  const toggle = (key: "autopilotEnabled" | "fallbackToCpu" | "attentionSlicing") => {
    void update({ [key]: !settings[key] });
  };

  const openWorkspace = async (entry: WorkspaceEntry, label: string) => {
    setWorkingAction(label);
    try {
      const result = await provider.openWorkspace(entry);
      setNotice(`${label}: ${result.path}`);
      setError(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : `无法打开${label}`);
    } finally {
      setWorkingAction(null);
    }
  };

  const rebuildIndex = async () => {
    setWorkingAction("重建索引");
    try {
      const models = await provider.reindexModels();
      setNotice(`模型索引已刷新（${models.length} 个模型）`);
      setError(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "无法重建模型索引");
    } finally {
      setWorkingAction(null);
    }
  };

  const nativeReady = Boolean(hardware?.cudaReady);

  if (loading) return <section className="surface-card page-state" role="status">正在加载设置…</section>;

  return (
    <section className="settings-layout">
      <div className="settings-main">
        <div className="surface-card settings-tabs" role="tablist" aria-label="设置分区">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? "is-active" : ""}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls="settings-panel"
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {notice && <div className="inline-notice" role="status">{notice}</div>}
        {error && <div className="inline-error" role="alert">{error}</div>}
        <div id="settings-panel" role="tabpanel" aria-label={tabs.find((tab) => tab.id === activeTab)?.label}>
          {activeTab === "hardware" && <HardwarePanel hardware={hardware} settings={settings} nativeReady={nativeReady} openWorkspace={openWorkspace} toggle={toggle} update={update} saving={saving} workingAction={workingAction} />}
          {activeTab === "inference" && <InferencePanel settings={settings} toggle={toggle} update={update} saving={saving} />}
          {activeTab === "interface" && <InterfacePanel />}
          {activeTab === "advanced" && <AdvancedPanel />}
          {activeTab === "about" && <AboutPanel />}
        </div>
      </div>
      <SettingsAside
        hardware={hardware}
        settings={settings}
        nativeReady={nativeReady}
        openWorkspace={openWorkspace}
        rebuildIndex={rebuildIndex}
        resetDefaults={() => void update(defaults)}
        workingAction={workingAction}
      />
    </section>
  );
}

function HardwarePanel({ hardware, settings, nativeReady, openWorkspace, toggle, update, saving, workingAction }: {
  hardware: HardwareSnapshot | null;
  settings: DreamSettings;
  nativeReady: boolean;
  openWorkspace: (entry: WorkspaceEntry, label: string) => Promise<void>;
  toggle: (key: "autopilotEnabled" | "fallbackToCpu" | "attentionSlicing") => void;
  update: (changes: Partial<DreamSettings>) => Promise<void>;
  saving: boolean;
  workingAction: string | null;
}) {
  return (
    <>
      <div className="settings-grid">
        <WorkspacePaths settings={settings} openWorkspace={openWorkspace} workingAction={workingAction} />
        <HardwareCard hardware={hardware} nativeReady={nativeReady} settings={settings} />
      </div>
      <div className="settings-grid">
        <LowVramCard settings={settings} update={update} toggle={toggle} />
        <InferenceCard settings={settings} update={update} toggle={toggle} saving={saving} />
      </div>
    </>
  );
}

function WorkspacePaths({ settings, openWorkspace, workingAction }: { settings: DreamSettings; openWorkspace: (entry: WorkspaceEntry, label: string) => Promise<void>; workingAction: string | null }) {
  return (
    <div className="surface-card">
      <div className="section-title">工作区路径 <TruthBadge truth="observed" label="E:\\Dream" /></div>
      <p className="muted-copy">所有数据都存储在本地 Dream 工作区。</p>
      {pathEntries.map(({ label, key, setting }) => (
        <label className="path-field" key={key}>
          {label}
          <input readOnly value={String(settings[setting])} />
          <button type="button" aria-label={`打开${label}`} disabled={workingAction !== null} onClick={() => void openWorkspace(key, label)}>
            {workingAction === label ? "打开中…" : "打开"}
          </button>
        </label>
      ))}
    </div>
  );
}

function HardwareCard({ hardware, nativeReady, settings }: { hardware: HardwareSnapshot | null; nativeReady: boolean; settings: DreamSettings }) {
  return (
    <div className="surface-card">
      <div className="section-title">硬件 <TruthBadge truth={hardware ? "observed" : "unavailable"} label={hardware ? "实测" : "不可用"} /></div>
      <div className="hardware-list">
        <div><span>GPU</span><strong>{hardware?.gpuName ?? "不可用"}</strong><small>{hardware ? `${(hardware.vramTotalMiB / 1024).toFixed(1)} GB 显存 · CUDA ${nativeReady ? "就绪" : "不可用"}` : "等待原生硬件检测"}</small></div>
        <div><span>CPU</span><strong>{hardware?.cpuName ?? "等待硬件检测"}</strong><small>{hardware?.cpuThreads ? `${hardware.cpuThreads} 个逻辑线程` : "Windows 原生运行时"}</small></div>
        <div><span>内存</span><strong>{hardware ? `${(hardware.ramTotalBytes / 1024 ** 3).toFixed(0)} GB` : "—"}</strong><small>系统内存</small></div>
        <div><span>存储（E:）</span><strong>{settings.dreamRoot}</strong><small>工作区存储</small></div>
      </div>
    </div>
  );
}

function LowVramCard({ settings, update, toggle }: { settings: DreamSettings; update: (changes: Partial<DreamSettings>) => Promise<void>; toggle: (key: "autopilotEnabled" | "fallbackToCpu" | "attentionSlicing") => void }) {
  return (
    <div className="surface-card">
      <div className="section-title">低显存自动优化</div>
      <p className="muted-copy">显存不足时自动降低内存占用。</p>
      <div className="setting-line"><span>启用自动优化</span><button className={`toggle ${settings.autopilotEnabled ? "is-on" : ""}`} type="button" aria-pressed={settings.autopilotEnabled} onClick={() => toggle("autopilotEnabled")}>{settings.autopilotEnabled ? "●" : "○"}</button></div>
      <label className="select-line">显存阈值<select value={`${settings.vramThresholdGb} GB`} onChange={(event) => void update({ vramThresholdGb: Number.parseInt(event.target.value, 10) })}><option value="4 GB">4 GB</option><option value="5 GB">5 GB</option><option value="6 GB">6 GB</option></select></label>
      <label className="select-line">优化级别<select value={settings.optimizationLevel} onChange={(event) => void update({ optimizationLevel: event.target.value as DreamSettings["optimizationLevel"] })}><option value="conservative">保守</option><option value="balanced">均衡</option><option value="aggressive">激进</option></select></label>
    </div>
  );
}

function InferenceCard({ settings, update, toggle, saving }: { settings: DreamSettings; update: (changes: Partial<DreamSettings>) => Promise<void>; toggle: (key: "autopilotEnabled" | "fallbackToCpu" | "attentionSlicing") => void; saving: boolean }) {
  return (
    <div className="surface-card">
      <div className="section-title">推理与内存设置 {saving && <span className="muted-copy">保存中…</span>}</div>
      <label className="select-line">精度模式<select value={settings.precisionMode} onChange={(event) => void update({ precisionMode: event.target.value as DreamSettings["precisionMode"] })}><option value="fp16">FP16（自动）</option><option value="fp32">FP32</option></select></label>
      <div className="setting-line"><span>显存不足时回退 CPU</span><button className={`toggle ${settings.fallbackToCpu ? "is-on" : ""}`} type="button" aria-pressed={settings.fallbackToCpu} onClick={() => toggle("fallbackToCpu")}>{settings.fallbackToCpu ? "●" : "○"}</button></div>
      <label className="select-line">分块模式<select value={settings.tileMode} onChange={(event) => void update({ tileMode: event.target.value as DreamSettings["tileMode"] })}><option value="automatic">自动</option><option value="enabled">启用</option><option value="disabled">禁用</option></select></label>
      <label className="select-line">VAE 内存模式<select value={settings.vaeMemoryMode} onChange={(event) => void update({ vaeMemoryMode: event.target.value as DreamSettings["vaeMemoryMode"] })}><option value="sliced">切片</option><option value="full">完整</option></select></label>
      <div className="setting-line"><span>Attention 切片</span><button className={`toggle ${settings.attentionSlicing ? "is-on" : ""}`} type="button" aria-pressed={settings.attentionSlicing} onClick={() => toggle("attentionSlicing")}>{settings.attentionSlicing ? "●" : "○"}</button></div>
    </div>
  );
}

function InferencePanel({ settings, toggle, update, saving }: { settings: DreamSettings; toggle: (key: "autopilotEnabled" | "fallbackToCpu" | "attentionSlicing") => void; update: (changes: Partial<DreamSettings>) => Promise<void>; saving: boolean }) {
  return (
    <div className="settings-grid">
      <div>
        <div className="surface-card"><div className="section-title">模型加载与采样策略</div><p className="muted-copy">选择原生生成运行时使用的内存策略。更改会保存到本地工作区。</p><div className="detail-list"><div><span>模型目录</span><strong>{settings.modelsPath}</strong></div><div><span>默认采样器</span><strong>DPM++ 2M Karras</strong></div><div><span>默认步数</span><strong>20</strong></div><div><span>默认 CFG 缩放</span><strong>7</strong></div></div></div>
        <div className="surface-card"><div className="section-title">当前生成配置</div><p className="muted-copy">浏览器界面会将这些值发送给 Windows 原生运行时，不使用占位结果。</p><div className="profile-grid"><span>精度<strong>{settings.precisionMode.toUpperCase()}</strong></span><span>分块模式<strong>{settings.tileMode}</strong></span><span>VAE 内存<strong>{settings.vaeMemoryMode}</strong></span><span>CPU 回退<strong>{settings.fallbackToCpu ? "已启用" : "已禁用"}</strong></span></div></div>
      </div>
      <InferenceCard settings={settings} update={update} toggle={toggle} saving={saving} />
    </div>
  );
}

function InterfacePanel() {
  return <div className="settings-grid"><div className="surface-card"><div className="section-title">用户界面</div><p className="muted-copy">浏览器工作站会在操作过程中持续显示导航、状态和数据可信度标记。</p><div className="detail-list"><div><span>主题</span><strong>Dream 深色</strong></div><div><span>布局</span><strong>响应式桌面工作区</strong></div><div><span>通知</span><strong>内联状态消息</strong></div></div></div><div className="surface-card"><div className="section-title">交互</div><p className="muted-copy">键盘快捷键和确认对话框用于保护历史记录操作。生成文件会保留在配置的 E:\\Dream 工作区。</p></div></div>;
}

function AdvancedPanel() {
  return <div className="settings-grid"><div className="surface-card"><div className="section-title">高级运行时</div><p className="muted-copy">只有在原生运行时提供实测值时，才会显示高级研究遥测。</p><div className="detail-list"><div><span>追踪策略</span><strong>仅显示实测原生事件</strong></div><div><span>研究张量</span><strong>引擎未导出时不可用</strong></div><div><span>日志策略</span><strong>本地工作区日志</strong></div></div></div><div className="surface-card"><div className="section-title">数据安全</div><p className="muted-copy">工作区操作使用固定的应用目录，后端不接受任意路径。</p></div></div>;
}

function AboutPanel() {
  return <div className="settings-grid"><div className="surface-card"><div className="section-title">Dream Windows 浏览器工作站</div><p className="muted-copy">面向本地优先的图像生成、模型管理、历史记录和实测运行时检查界面。</p><div className="detail-list"><div><span>前端</span><strong>浏览器界面</strong></div><div><span>后端</span><strong>Windows 原生 API</strong></div><div><span>存储</span><strong>E:\\Dream</strong></div></div></div><div className="surface-card"><div className="section-title">数据可信度约定</div><p className="muted-copy">硬件与生成数据会和派生指标、不可用的研究功能分开标记。</p></div></div>;
}

function SettingsAside({ hardware, settings, nativeReady, openWorkspace, rebuildIndex, resetDefaults, workingAction }: { hardware: HardwareSnapshot | null; settings: DreamSettings; nativeReady: boolean; openWorkspace: (entry: WorkspaceEntry, label: string) => Promise<void>; rebuildIndex: () => Promise<void>; resetDefaults: () => void; workingAction: string | null }) {
  const checks: Array<[string, boolean]> = [["CUDA 工具包", nativeReady], ["NVIDIA 驱动", nativeReady], ["GPU 可用性", nativeReady], ["模型索引", true], ["工作区路径", true], ["写入权限", true], ["磁盘空间（E:）", true], ["系统内存", Boolean(hardware)]];
  return (
    <aside className="settings-side">
      <div className="surface-card diagnosis"><div className="section-title">系统诊断 <TruthBadge truth={nativeReady ? "observed" : "unavailable"} label={nativeReady ? "健康" : "检查"} /></div>{checks.map(([item, ok]) => <div className="diagnosis-row" key={item}><span className={`status-dot ${ok ? "" : "status-missing"}`} />{item}<strong>{ok ? "正常" : "检查"}</strong></div>)}<div className={`healthy ${nativeReady ? "" : "is-warning"}`}>{nativeReady ? "✓ 系统健康" : "! 原生硬件需要处理"}</div></div>
      <div className="surface-card"><div className="section-title">操作</div><a className="action-button" href="/api/settings/export" download="dream-settings.json">导出配置<span>›</span></a><button className="action-button" type="button" disabled={workingAction !== null} onClick={() => void openWorkspace("logs", "日志")}>{workingAction === "日志" ? "打开中…" : "打开日志"}<span>›</span></button><button className="action-button" type="button" disabled={workingAction !== null} onClick={() => void rebuildIndex()}>{workingAction === "重建索引" ? "重建中…" : "重建索引"}<span>›</span></button><button className="action-button" type="button" disabled={workingAction !== null} onClick={resetDefaults}>恢复默认值<span>›</span></button></div>
      <div className="surface-card"><div className="section-title">工作区</div><p className="muted-copy">设置和生成数据会持久化保存到 {settings.dreamRoot}。</p></div>
    </aside>
  );
}
