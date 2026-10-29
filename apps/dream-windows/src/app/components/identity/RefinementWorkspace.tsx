import { useCallback, useEffect, useRef, useState } from "react";
import { refinementApi, RefinementHttpError } from "../../../providers/refinement-api";
import type { RefinementMode, RefinementRequest, RefinementSnapshot, RefinementVersion } from "../../../providers/refinement-api";
import { useDeletedImageIds } from "../../image-deletion";
import "./RefinementWorkspace.css";

type Props = { sourceJobId: string; onClose: () => void };
const modeLabels: Record<RefinementMode, string> = { restore: "人脸修复", redraw: "局部重绘", "reference-anchor": "参考脸对齐 · 保留中央五官", "edge-lighting": "边缘光照协调" };
const stateLabels: Record<RefinementVersion["state"], string> = { queued: "排队中", running: "精修中", complete: "完成", failed: "失败", cancelled: "已取消" };
const active = (item: RefinementVersion) => item.state === "queued" || item.state === "running";
const availableModes = (data: RefinementSnapshot): RefinementMode[] => [...new Set(data.modes ?? ["restore"])].filter((mode): mode is RefinementMode => Object.hasOwn(modeLabels, mode));
const errorText = (reason: unknown) => reason instanceof Error ? reason.message : "精修请求失败";

const metricRecord = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const measuredNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const measuredDuration = (milliseconds: number) => milliseconds >= 1000 ? `${Number((milliseconds / 1000).toFixed(1))} 秒` : `${milliseconds} 毫秒`;

function RefinementMeasurements({ version, label }: { version: RefinementVersion; label: string }) {
  const metrics = metricRecord(version.metrics);
  const phases = metricRecord(metrics.phasesMs);
  const phaseLabels: Record<string, string> = { read: "读取父图", load: "加载模型", polish: "执行精修", diagnostics: "像素诊断", save: "保存图像" };
  const measuredPhases = Object.entries(phaseLabels).filter(([name]) => measuredNumber(phases[name]));
  const diagnostics = metricRecord(metrics.diagnostics);
  const retention = diagnostics.schemaVersion === 1 ? metricRecord(diagnostics.retention) : {};
  const regions = Object.entries({ whole: "全图", protected: "保护区", outsideEdit: "编辑掩膜外" }).map(([name, title]) => {
    const region = metricRecord(retention[name]);
    const count = region.pixelCount, changed = region.changedPixels;
    const valid = measuredNumber(count) && Number.isSafeInteger(count) && measuredNumber(changed) && Number.isSafeInteger(changed) && changed <= count;
    return { title, count: valid ? count : null, changed: valid ? changed : null };
  });
  if (!measuredNumber(metrics.durationMs) && !measuredPhases.length && !regions.some(region => region.count !== null)) return null;
  const baseline = typeof diagnostics.baselineLabel === "string" && diagnostics.baselineLabel ? diagnostics.baselineLabel : "未返回";
  const candidate = typeof diagnostics.candidateLabel === "string" && diagnostics.candidateLabel ? diagnostics.candidateLabel : "未返回";
  return <details className="refinement-measurements"><summary>{label} · 实测记录</summary>
    <p className="refinement-note">像素变化对照，不代表人物相似度或画质评分。</p>
    {measuredNumber(metrics.durationMs) && <p>总耗时：{measuredDuration(metrics.durationMs)}</p>}
    {measuredPhases.length > 0 && <table aria-label={`${label} 阶段耗时`}><thead><tr><th>阶段</th><th>实测耗时</th></tr></thead>
      <tbody>{measuredPhases.map(([name, title]) => <tr key={name}><th scope="row">{title}</th><td>{measuredDuration(phases[name] as number)}</td></tr>)}</tbody></table>}
    <p>比较基准：{baseline} → {candidate}</p>
    <table aria-label={`${label} 区域像素变化`}><thead><tr><th>区域</th><th>像素总数</th><th>变化像素</th></tr></thead>
      <tbody>{regions.map(region => <tr key={region.title}><th scope="row">{region.title}</th><td>{region.count ?? "未返回"}</td><td>{region.changed ?? "未返回"}</td></tr>)}</tbody></table>
    <p className="refinement-note">区域按服务返回的掩膜统计；未返回的计数不表示零变化。</p>
  </details>;
}

export function RefinementWorkspace(props: Props) {
  const deleted = useDeletedImageIds();
  // A source change gets fresh request guards, inputs and image error state.
  return deleted.has(props.sourceJobId) ? null : <RefinementSession key={props.sourceJobId} {...props} />;
}

function RefinementSession({ sourceJobId, onClose }: Props) {
  const [data, setData] = useState<RefinementSnapshot | null>(null);
  const dataRef = useRef<RefinementSnapshot | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [synced, setSynced] = useState(false);
  const [gone, setGone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<RefinementMode | "">("");
  const [strength, setStrength] = useState("0.35");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [seed, setSeed] = useState("0");
  const [retryRequest, setRetryRequest] = useState<RefinementRequest | null>(null);
  const [brokenImages, setBrokenImages] = useState<Set<string>>(new Set());
  const heading = useRef<HTMLHeadingElement>(null);
  const control = useRef({ mounted: false, gone: false, busy: false, sequence: 0,
    timer: undefined as number | undefined, read: null as AbortController | null, action: null as AbortController | null });

  const accept = useCallback((next: RefinementSnapshot) => {
    dataRef.current = next;
    setData(next); setSynced(true); setReadError(null);
    const modes = availableModes(next);
    setMode(current => modes.includes(current as RefinementMode) ? current : modes.find(value => value === next.defaultMode) ?? modes[0] ?? "");
    setRetryRequest(current => current && current.parentVersionId === next.selectedVersionId && modes.includes(current.mode) ? current : null);
  }, []);

  const refresh = useCallback(async function readVersions() {
    const state = control.current;
    if (!state.mounted || state.gone || state.busy || state.read) return;
    window.clearTimeout(state.timer);
    const request = new AbortController();
    state.read = request;
    const sequence = ++state.sequence;
    try {
      const next = await refinementApi.list(sourceJobId, request.signal);
      if (state.mounted && !request.signal.aborted && sequence === state.sequence) accept(next);
    } catch (reason) {
      if (!state.mounted || request.signal.aborted || sequence !== state.sequence) return;
      setReadError(errorText(reason)); setSynced(false);
      if (reason instanceof RefinementHttpError && (reason.status === 404 || reason.status === 410)) {
        state.gone = true; setGone(true); setData(null); dataRef.current = null;
      }
    } finally {
      if (state.read === request) {
        state.read = null;
        if (state.mounted && !state.gone && !state.busy) {
          state.timer = window.setTimeout(() => void readVersions(), dataRef.current?.versions.some(active) ? 1500 : 5000);
        }
      }
    }
  }, [accept, sourceJobId]);

  useEffect(() => {
    const state = control.current;
    state.mounted = true;
    const opener = document.activeElement;
    heading.current?.focus();
    void refresh();
    return () => {
      state.mounted = false; state.sequence += 1;
      window.clearTimeout(state.timer);
      state.read?.abort(); state.read = null;
      state.action?.abort(); state.action = null;
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, [refresh]);

  const mutate = async (operation: (signal: AbortSignal) => Promise<RefinementSnapshot | RefinementVersion>, submission?: RefinementRequest) => {
    const state = control.current;
    if (!state.mounted || state.busy || state.gone) return;
    state.busy = true; setBusy(true); setActionError(null);
    state.sequence += 1;
    window.clearTimeout(state.timer);
    state.read?.abort(); state.read = null;
    const request = new AbortController(); state.action = request;
    let reconcile = false;
    try {
      const result = await operation(request.signal);
      if (!state.mounted || request.signal.aborted) return;
      if ("versions" in result) accept(result);
      else if (dataRef.current) {
        const existing = dataRef.current.versions;
        accept({ ...dataRef.current, versions: existing.some(item => item.id === result.id)
          ? existing.map(item => item.id === result.id ? result : item) : [...existing, result] });
      }
      if (submission) setRetryRequest(null);
    } catch (reason) {
      if (!state.mounted || request.signal.aborted) return;
      setActionError(`${errorText(reason)}${submission ? "；提交结果未确认，请先核对版本，再重试本次提交。" : ""}`);
      setSynced(false); reconcile = true;
      if (submission) setRetryRequest(submission);
    } finally {
      if (state.mounted && !request.signal.aborted) {
        state.busy = false; state.action = null; setBusy(false);
        if (reconcile) void refresh();
        else state.timer = window.setTimeout(() => void refresh(), dataRef.current?.versions.some(active) ? 1500 : 5000);
      }
    }
  };

  const versions = data?.versions ?? [];
  const refinements = versions.filter(item => item.id !== "result" && item.id !== "original");
  const versionLabel = (id: string | null) => {
    if (id === "result") return "生成结果";
    if (id === "original") return "生成原图";
    const index = refinements.findIndex(item => item.id === id);
    return index >= 0 ? `精修 ${index + 1}` : id ?? "未记录";
  };
  const selected = versions.find(item => item.id === data?.selectedVersionId);
  const imageKey = (item: RefinementVersion) => `${item.id}:${item.imageUrl}`;
  const readable = (item: RefinementVersion) => item.state === "complete" && !!item.imageUrl && !brokenImages.has(imageKey(item));
  const modes = data ? availableModes(data) : [];
  const hasActive = versions.some(active);
  const edgeLighting = mode === "edge-lighting";
  // Edge lighting never diffuses, even on a diffusion-capable source. Older
  // services omit this capability; retain their inputs for the other modes.
  const usesDiffusion = !edgeLighting && data?.usesDiffusion !== false;
  const plainRestore = !usesDiffusion && mode === "restore";
  const formDisabled = busy || hasActive || !synced || gone;
  const valid = strength.trim() !== "" && Number(strength) >= 0.15 && Number(strength) <= 0.65
    && (!usesDiffusion || seed.trim() !== "" && Number.isInteger(Number(seed)) && Number(seed) >= 0 && Number(seed) <= 2147483647);
  const canSubmit = !formDisabled && valid && modes.includes(mode as RefinementMode) && !!selected && readable(selected);
  const edit = (setter: (value: string) => void, value: string) => { setter(value); setRetryRequest(null); };
  const select = (id: string) => {
    // accept() discards the retry only after a different parent is confirmed.
    void mutate(signal => refinementApi.select(sourceJobId, id, signal));
  };
  const submit = (retry = false) => {
    if (!canSubmit || !data || !mode || control.current.busy || !retry && retryRequest) return;
    const body = retry ? retryRequest : { sourceJobId, parentVersionId: data.selectedVersionId, mode,
      strength: Number(strength), prompt: usesDiffusion ? prompt : "", negativePrompt: usesDiffusion ? negativePrompt : "",
      seed: usesDiffusion ? Number(seed) : 0, requestId: crypto.randomUUID() };
    if (body) void mutate(signal => refinementApi.create(body, signal), body);
  };

  return <section className="surface-card refinement-workspace" aria-label="独立精修工作区">
    <header className="refinement-heading"><div><h2 ref={heading} tabIndex={-1}>独立精修</h2>
      <p>每次只修一轮。选择一个可用版本作为下一轮父图，原图和已完成版本始终保留。</p></div>
      <button type="button" className="secondary-button" onClick={onClose}>关闭精修</button></header>
    <p className="refinement-note">人脸区域由当前参考自动定位。回到原图或结果仅切换工作区选择，不覆盖历史主图。</p>
    {readError && <div className="refinement-error" role="alert">{readError}{!gone && <button type="button" className="secondary-button" disabled={busy} onClick={() => void refresh()}>重试读取版本</button>}</div>}
    {actionError && <p className="refinement-error" role="alert">{actionError}</p>}
    {!data && !readError && <p role="status">正在读取精修版本…</p>}
    {data && <>
      <div className="refinement-body">
        <figure className="refinement-preview">
          {selected && readable(selected) ? <a href={selected.imageUrl!} target="_blank" rel="noreferrer"><img key={imageKey(selected)} src={selected.imageUrl!} alt="当前精修图像" decoding="async"
            onError={() => setBrokenImages(previous => new Set([...previous, imageKey(selected)]))} /></a>
            : <div role="status">当前版本图片不可用，请选择其他已完成版本。
              {selected?.imageUrl && brokenImages.has(imageKey(selected)) && <button type="button" className="secondary-button"
                onClick={() => setBrokenImages(previous => { const next = new Set(previous); next.delete(imageKey(selected)); return next; })}>重试当前图像</button>}
            </div>}
          <figcaption>当前父图：{versionLabel(data.selectedVersionId)} · 点击图像查看原尺寸</figcaption>
        </figure>
        <form className="refinement-form" onSubmit={event => { event.preventDefault(); submit(); }}>
          <fieldset disabled={formDisabled}><legend>下一轮精修</legend>
            <label>精修模式<select value={mode} onChange={event => { setMode(event.target.value as RefinementMode); setRetryRequest(null); }}>
              {!modes.length && <option value="">没有可用的精修模式</option>}
              {modes.map(value => <option value={value} key={value}>{modeLabels[value]}</option>)}
            </select></label>
            {data.modes === undefined && <p className="refinement-note">服务未提供模式列表，暂用人脸修复。</p>}
            <label>{edgeLighting ? "协调强度" : plainRestore ? "细节修复强度" : "精修强度"}<input type="number" min="0.15" max="0.65" step="0.01" value={strength} onChange={event => edit(setStrength, event.target.value)} /></label>
            {plainRestore && <p className="refinement-note">强度仅调节 GFPGAN 细节修复的混合比例；身份回贴始终执行。</p>}
            {edgeLighting && <p className="refinement-note">仅微调羽化皮肤边缘环的亮度，RGB 调整不超过 ±8；中央五官与环外像素保持不变。</p>}
            {usesDiffusion ? <>
              <label>精修提示词<textarea rows={3} value={prompt} onChange={event => edit(setPrompt, event.target.value)} /></label>
              <label>精修负面提示词<textarea rows={2} value={negativePrompt} onChange={event => edit(setNegativePrompt, event.target.value)} /></label>
              <label>精修种子<input type="number" min="0" max="2147483647" step="1" value={seed} onChange={event => edit(setSeed, event.target.value)} /></label>
            </> : <p className="refinement-note">{edgeLighting ? "边缘光照协调不使用提示词和随机种子" : "身份修复不使用提示词和随机种子"}</p>}
          </fieldset>
          {!valid && <p className="refinement-error">强度须为 0.15–0.65{usesDiffusion ? "，种子须为 0–2147483647 的整数。" : "。"}</p>}
          {hasActive && <p role="status">有精修版本正在处理，完成或取消后可继续。</p>}
          <button type="submit" className="primary-button" disabled={!canSubmit || !!retryRequest}>精修一轮</button>
          {retryRequest && <button type="button" className="secondary-button" disabled={!canSubmit} onClick={() => submit(true)}>重试本次提交</button>}
        </form>
      </div>
      <div className="refinement-versions" role="group" aria-label="精修版本与父图选择">
        {versions.map(item => <article className={`refinement-version${item.id === data.selectedVersionId ? " is-selected" : ""}`} key={item.id}>
          <button type="button" className="secondary-button" aria-pressed={item.id === data.selectedVersionId} disabled={busy || !readable(item)}
            onClick={() => select(item.id)}>{item.id === "result" ? "回到生成结果" : item.id === "original" ? "回到生成原图" : `选择${versionLabel(item.id)}`}</button>
          <span>{stateLabels[item.state]}</span>
          {item.id !== "result" && item.id !== "original" && <small>父图：{versionLabel(item.parentVersionId)} · {item.createdAt}</small>}
          {item.message && item.message !== item.state && <p>{item.message}</p>}
          {item.error && <p className="refinement-error">{item.error}</p>}
          <RefinementMeasurements version={item} label={versionLabel(item.id)} />
          {active(item) && <button type="button" className="danger-button" disabled={busy} onClick={() => void mutate(signal => refinementApi.cancel(item.id, signal))}>取消{versionLabel(item.id)}</button>}
        </article>)}
      </div>
    </>}
  </section>;
}
