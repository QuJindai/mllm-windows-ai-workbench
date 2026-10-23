import type { IdentityBatchRequest } from "../../../domain/identity";

export type BatchSettings = Pick<IdentityBatchRequest, "count" | "stepValues" | "previewEvery">;
export const defaultBatchSettings: BatchSettings = { count: 1, previewEvery: 0 };
export function validBatchSettings(value: BatchSettings): boolean {
  const steps = value.stepValues ?? [];
  return Number.isInteger(value.count) && value.count >= 1 && value.count <= 8
    && steps.length <= 4 && new Set(steps).size === steps.length && steps.every((step) => Number.isInteger(step) && step >= 1 && step <= 50)
    && value.count * (steps.length || 1) <= 16 && [0, 5, 10].includes(value.previewEvery);
}

export function BatchControls({ value, onChange }: { value: BatchSettings; onChange: (value: BatchSettings) => void }) {
  const selected = value.stepValues ?? [];
  const choices = [...new Set([20, 28, 36, ...selected])].sort((a, b) => a - b);
  return <section className="identity-batch-controls" aria-label="批次参数">
    <h2>4 · 批次与步数对照</h2>
    <label>生成张数<input type="number" min={1} max={8} step={1} value={Number.isFinite(value.count) ? value.count : ""} onChange={(event) => onChange({ ...value, count: event.target.value === "" ? NaN : Number(event.target.value) })} /></label>
    <div role="group" aria-label="可选步数对照" className="identity-step-options">{choices.map((step) => <label key={step}>
      <input type="checkbox" checked={selected.includes(step)} onChange={(event) => {
        const stepValues = event.target.checked ? [...selected, step].sort((a, b) => a - b) : selected.filter((item) => item !== step);
        onChange({ count: value.count, previewEvery: value.previewEvery, ...(stepValues.length ? { stepValues } : {}) });
      }} />{step} 步
    </label>)}</div>
    <p className="identity-note">不勾选时使用上方步数。勾选后，同一种子比较不同步数；不同张由服务固定并递增种子，串行复用模型。</p>
    <p aria-live="polite">本批总数：{Number.isFinite(value.count) ? value.count * (selected.length || 1) : "—"} 张（最多 16 张）</p>
    {!validBatchSettings(value) && <p className="identity-error">张数须为 1–8 的整数；步数对照矩阵不能超过 16 张。</p>}
    <label>中间预览频率<select value={value.previewEvery} onChange={(event) => onChange({ ...value, previewEvery: Number(event.target.value) as 0 | 5 | 10 })}>
      <option value={0}>关闭预览</option><option value={5}>每 5 步</option><option value={10}>每 10 步</option>
    </select></label>
    <p className="identity-note">中间预览为真实采样的低分辨率解码，会增加耗时；关闭后不进行额外预览解码。</p>
  </section>;
}
