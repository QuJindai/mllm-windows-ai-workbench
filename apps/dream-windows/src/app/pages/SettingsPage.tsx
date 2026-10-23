import { useEffect, useState } from "react";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { DreamSettings, WorkspaceEntry } from "../../domain/settings";
import { useDreamProvider } from "../providers";
import { TruthBadge } from "../components/TruthBadge";
import { OperationsDiagnostics } from "../components/OperationsDiagnostics";
import { saveUiPreferences, useUiPreferences } from "../ui-preferences";
import type { UiPreferences } from "../ui-preferences";
import type { RuntimeCapabilities } from "../../domain/trace";

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
        <OperationsDiagnostics enabled={provider.mode === "backend"} />
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
        <div className="surface-card"><div className="section-title">模型加载与采样策略</div><p className="muted-copy">选择原生生成运行时使用的内存策略。更改会保存到本地工作区。</p><div className="detail-list"><div><span>模型目录</span><strong>{settings.modelsPath}</strong></div><div><span>采样器 / 步数 / CFG</span><strong>以生成页当前参数和所选预设为准</strong></div></div></div>
        <div className="surface-card"><div className="section-title">当前生成配置</div><p className="muted-copy">浏览器界面会将这些值发送给 Windows 原生运行时，不使用占位结果。</p><div className="profile-grid"><span>精度<strong>{settings.precisionMode.toUpperCase()}</strong></span><span>分块模式<strong>{settings.tileMode}</strong></span><span>VAE 内存<strong>{settings.vaeMemoryMode}</strong></span><span>CPU 回退<strong>{settings.fallbackToCpu ? "已启用" : "已禁用"}</strong></span></div></div>
      </div>
      <InferenceCard settings={settings} update={update} toggle={toggle} saving={saving} />
    </div>
  );
}

function InterfacePanel() {
  const preferences = useUiPreferences();
  const [notice, setNotice] = useState("");
  const update = (changes: Partial<UiPreferences>) => {
    try { saveUiPreferences(changes); setNotice("已保存到当前浏览器，立即生效。"); }
    catch { setNotice("浏览器存储不可用，设置未保存。"); }
  };
  return <div className="settings-grid"><div className="surface-card">
    <div className="section-title">用户界面</div>
    <label className="select-line">文字大小<select value={preferences.textSize} onChange={(event) => update({ textSize: event.target.value as UiPreferences["textSize"] })}><option value="standard">标准</option><option value="large">大字</option></select></label>
    <label className="select-line">界面密度<select value={preferences.density} onChange={(event) => update({ density: event.target.value as UiPreferences["density"] })}><option value="comfortable">舒适</option><option value="compact">紧凑</option></select></label>
    <label className="select-line">动态效果<select value={preferences.reduceMotion ? "reduced" : "system"} onChange={(event) => update({ reduceMotion: event.target.value === "reduced" })}><option value="system">跟随系统</option><option value="reduced">减少动态效果</option></select></label>
    {notice && <p className="ui-setting-message" role="status">{notice}</p>}
  </div><div className="surface-card"><div className="section-title">交互</div><p className="muted-copy">设置仅作用于当前浏览器。生成任务切换页面后继续执行；窄屏下可通过顶部导航切换页面。</p><p className="muted-copy">主题：Dream 深色 · 语言：简体中文</p></div></div>;
}

function AdvancedPanel() {
  const preferences = useUiPreferences();
  const [notice, setNotice] = useState("");
  const update = (changes: Partial<UiPreferences>) => {
    try { saveUiPreferences(changes); setNotice("刷新策略已保存。"); }
    catch { setNotice("浏览器存储不可用，设置未保存。"); }
  };
  return <div className="settings-grid"><div className="surface-card"><div className="section-title">历史刷新策略</div>
    <label className="select-line">自动刷新<select value={preferences.historyAutoRefresh ? "on" : "off"} onChange={(event) => update({ historyAutoRefresh: event.target.value === "on" })}><option value="on">页面可见时刷新</option><option value="off">仅手动刷新</option></select></label>
    <label className="select-line">刷新间隔<select disabled={!preferences.historyAutoRefresh} value={preferences.historyInterval} onChange={(event) => update({ historyInterval: Number(event.target.value) as UiPreferences["historyInterval"] })}>{[15, 30, 60].map((seconds) => <option key={seconds} value={seconds}>{seconds} 秒</option>)}</select></label>
    <p className="muted-copy">离开历史页或切到其他浏览器标签后暂停刷新。也可以随时点击历史页的“刷新”。</p>
    {notice && <p className="ui-setting-message" role="status">{notice}</p>}
  </div><ResearchCaptureStatus /></div>;
}

function ResearchCaptureStatus() {
  const provider = useDreamProvider();
  const [capabilities, setCapabilities] = useState<RuntimeCapabilities | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setCapabilities(null);
    setLoading(true);
    setError("");
    void provider.getCapabilities().then((value) => { if (active) setCapabilities(value); })
      .catch(() => { if (active) setError("研究采集能力读取失败，请刷新重试。"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [provider, refreshVersion]);
  const entries = [
    { label: "H6 条件影响", capability: capabilities?.conditioningInfluence },
    { label: "H7 自注意力", capability: capabilities?.selfAttention },
    { label: "H7 交叉注意力", capability: capabilities?.attention },
  ];
  return <section className="surface-card" aria-label="研究采集">
    <div className="section-title">研究采集</div>
    <p className="muted-copy">在生成页选择“显微镜采集”级别：H6 采集条件影响与潜空间；H7 还采集自注意力和交叉注意力。研究采集增加额外前向计算、内存及写入开销。</p>
    <div className="h7-matrix-scroll"><table className="h7-matrix" aria-label="研究采集能力"><thead><tr><th>采集类型</th><th>当前能力</th></tr></thead><tbody>{entries.map(({ label, capability }) => {
      const ready = capability?.available === true && capability.truth === "observed";
      const unknown = !capability || capability.message === "能力状态未返回" || (capability.available && !ready);
      return <tr key={label}><th>{label}</th><td><TruthBadge truth={ready ? "observed" : "unavailable"} label={loading ? "读取中" : ready ? "采集已就绪" : unknown ? "未确认" : "不可用"} /></td></tr>;
    })}</tbody></table></div>
    <p className="muted-copy">各项状态独立读取后端能力声明。未返回能力或读取失败时保持未确认；能力就绪不代表每条历史记录都已采集，显微镜仍按有效产物显示数据。</p>
    <p className="muted-copy">旧记录中未采集的张量无法补出。条件影响是分块与完整上下文预测的诊断比较，不代表生产路径对分块预测取算术平均。</p>
    {error && <p role="status">{error}</p>}
    <button type="button" className="secondary-button" disabled={loading} onClick={() => setRefreshVersion((value) => value + 1)}>刷新采集能力</button>
  </section>;
}

function AboutPanel() {
  return <div className="settings-grid"><div className="surface-card"><div className="section-title">Dream Windows 浏览器工作站</div><p className="muted-copy">面向本地优先的图像生成、模型管理、历史记录和实测运行时检查界面。</p><div className="detail-list"><div><span>前端</span><strong>浏览器界面</strong></div><div><span>后端</span><strong>Windows 原生 API</strong></div><div><span>存储</span><strong>E:\\Dream</strong></div></div></div><div className="surface-card"><div className="section-title">数据可信度约定</div><p className="muted-copy">硬件与生成数据会和派生指标、不可用的研究功能分开标记。</p></div></div>;
}

function SettingsAside({ hardware, settings, nativeReady, openWorkspace, rebuildIndex, resetDefaults, workingAction }: { hardware: HardwareSnapshot | null; settings: DreamSettings; nativeReady: boolean; openWorkspace: (entry: WorkspaceEntry, label: string) => Promise<void>; rebuildIndex: () => Promise<void>; resetDefaults: () => void; workingAction: string | null }) {
  const checks: Array<[string, boolean | null, string]> = [
    ["CUDA 工具包", null, "未独立检测"],
    ["NVIDIA 驱动", hardware?.driverVersion ? true : null, hardware?.driverVersion ?? "未返回版本"],
    ["GPU 可用性", hardware ? nativeReady : null, hardware ? (nativeReady ? "就绪" : "不可用") : "未检测"],
    ["模型索引", null, "请在模型页核查"],
    ["工作区路径", null, settings.dreamRoot],
    ["写入权限", null, "未独立检测"],
    ["磁盘空间（E:）", hardware?.eDriveFreeBytes == null ? null : hardware.eDriveFreeBytes > 1024 ** 3, hardware?.eDriveFreeBytes == null ? "未返回容量" : `可用 ${(hardware.eDriveFreeBytes / 1024 ** 3).toFixed(1)} GB`],
    ["系统内存", hardware ? hardware.ramTotalBytes > 0 : null, hardware ? `${Math.round(hardware.ramTotalBytes / 1024 ** 3)} GB` : "未检测"],
  ];
  return (
    <aside className="settings-side">
      <div className="surface-card diagnosis"><div className="section-title">系统诊断 <TruthBadge truth={hardware?.truth ?? "unavailable"} label="检测快照" /></div>{checks.map(([item, ok, detail]) => <div className="diagnosis-row" key={item}><span className={`status-dot ${ok === null ? "status-unknown" : ok ? "" : "status-missing"}`} />{item}<strong>{detail}</strong></div>)}<p className="muted-copy">未检测的项目不参与健康判断。CUDA 可用并不代表工具包、磁盘和权限均已验证。</p></div>
      <div className="surface-card"><div className="section-title">操作</div><a className="action-button" href="/api/settings/export" download="dream-settings.json">导出配置<span>›</span></a><button className="action-button" type="button" disabled={workingAction !== null} onClick={() => void openWorkspace("logs", "日志")}>{workingAction === "日志" ? "打开中…" : "打开日志"}<span>›</span></button><button className="action-button" type="button" disabled={workingAction !== null} onClick={() => void rebuildIndex()}>{workingAction === "重建索引" ? "重建中…" : "重建索引"}<span>›</span></button><button className="action-button" type="button" disabled={workingAction !== null} onClick={resetDefaults}>恢复默认值<span>›</span></button></div>
      <div className="surface-card"><div className="section-title">工作区</div><p className="muted-copy">设置和生成数据会持久化保存到 {settings.dreamRoot}。</p></div>
    </aside>
  );
}
