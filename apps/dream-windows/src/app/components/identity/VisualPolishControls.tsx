import { useId } from "react";
import { validAnimeStrength, validVisualAnchorStrength, validVisualPolishMode, validVisualPolishPasses } from "../../../domain/identity";
import type { IdentityReference, IdentityRequest, IdentityStatus } from "../../../domain/identity";

type Options = Pick<IdentityRequest, "facePolish" | "animeDenoiseStrength" | "visualPolishPrompt" | "visualPolishNegativePrompt"
  | "visualPolishMode" | "visualAnchorStrength" | "visualPolishPasses">;
export function VisualPolishControls({ value, capability, reference, faceIndex, onChange }: {
  value: Options; capability: IdentityStatus["visualPolish"]; reference?: IdentityReference; faceIndex: number | null;
  onChange: (value: Options) => void;
}) {
  const hint = useId(), availability = useId(), anchorAvailability = useId();
  const ready = capability?.ready === true;
  const anchorUnavailable = capability?.referenceAnchorReady === false;
  const anchorMessage = capability?.referenceAnchorMessage || (anchorUnavailable ? "对齐依赖未就绪。"
    : capability?.referenceAnchorReady === true ? "对齐依赖已就绪。" : "");
  return <section className="identity-face-polish-controls" aria-label="可选生成后修脸">
    <label className="identity-polish-checkbox">
      <input type="checkbox" checked={value.facePolish} disabled={!ready} aria-describedby={`${hint} ${availability}`}
        onChange={event => onChange({ ...value, facePolish: event.target.checked })} />生成后修脸（可选）
    </label>
    <p id={hint} className="identity-note">默认关闭。先生成构图与画风，再按所选模式处理脸部。保留原图与阶段图供对照，第二轮不一定更好。失败保留原图。</p>
    <p id={availability} className="identity-note">{capability?.message || "服务未报告视觉参考局部重绘能力，当前不可用。"}</p>
    {anchorMessage && <p id={anchorAvailability} className="identity-note">参考脸对齐：{anchorMessage}</p>}
    {value.facePolish && <>
      <p className="identity-note">重绘参考：{reference && faceIndex !== null ? `${reference.name} · 人脸 ${faceIndex + 1}` : "请先选择当前参考图与人脸"}</p>
      <label>修脸模式<select disabled={!ready} aria-describedby={anchorMessage ? anchorAvailability : undefined} value={value.visualPolishMode ?? "redraw"} onChange={event => {
        const mode = event.target.value;
        if (validVisualPolishMode(mode) && (mode !== "reference-anchor" || !anchorUnavailable)) onChange({ ...value, visualPolishMode: mode,
          ...(mode === "reference-anchor" ? { animeDenoiseStrength: .25 } : {}) });
      }}>
        <option value="redraw">局部重绘</option><option value="reference-anchor" disabled={anchorUnavailable}>参考脸对齐</option>
      </select></label>
      {value.visualPolishMode === "reference-anchor" && anchorUnavailable && <p className="identity-error" role="alert">参考脸对齐依赖未就绪，请切换为局部重绘，或关闭修脸后继续生成。</p>}
      {value.visualPolishMode === "reference-anchor" && <>
        <label>参考脸融合强度<input type="number" min={.3} max={1} step={.05} disabled={!ready}
          value={Number.isFinite(value.visualAnchorStrength ?? .95) ? value.visualAnchorStrength ?? .95 : ""}
          onChange={event => onChange({ ...value, visualAnchorStrength: event.target.value === "" ? NaN : Number(event.target.value) })} /></label>
        <p className="identity-note">0.3–1，默认 0.95。对齐会使用当前参考图的脸部像素，保留中央五官，只融合脸部边缘；第二轮也不重画五官。适合清晰、角度接近的参考。</p>
      </>}
      {(value.visualPolishMode ?? "redraw") === "redraw" && <p className="identity-note">局部重绘会改变脸部和五官，不保证人物一致性；请对照原图与各阶段结果选择。</p>}
      <label>修脸轮次<select disabled={!ready} value={value.visualPolishPasses ?? 1} onChange={event => {
        const passes = Number(event.target.value);
        if (validVisualPolishPasses(passes)) onChange({ ...value, visualPolishPasses: passes });
      }}>
        <option value={1}>1 轮 · 融合（默认）</option><option value={2}>2 轮 · 融合后轻量细化</option>
      </select></label>
      <p className="identity-note">第二轮使用第一轮结果，去噪固定 0.15；不重新生成全图。</p>
      <label>重绘强度<input type="number" min={.15} max={.65} step={.05} disabled={!ready}
        value={Number.isFinite(value.animeDenoiseStrength ?? .35) ? value.animeDenoiseStrength ?? .35 : ""}
        onChange={event => onChange({ ...value, animeDenoiseStrength: event.target.value === "" ? NaN : Number(event.target.value) })} /></label>
      <p className="identity-note">第一轮去噪 0.15–0.65，局部重绘默认 0.35；切换到参考脸对齐时设为 0.25，可继续调整。{value.visualPolishMode === "reference-anchor" ? "对齐模式仅调整边缘融合，中央五官受保护。" : "越高改变越大。"}</p>
      <label>修脸提示词<textarea maxLength={2000} rows={2} disabled={!ready}
        placeholder="留空使用动漫脸部细节提示词，不继承场景构图"
        value={value.visualPolishPrompt ?? ""} onChange={event => onChange({ ...value, visualPolishPrompt: event.target.value })} /></label>
      <label>修脸反向提示词<textarea maxLength={2000} rows={2} disabled={!ready}
        placeholder="留空使用脸部模糊、变形等默认排除项"
        value={value.visualPolishNegativePrompt ?? ""} onChange={event => onChange({ ...value, visualPolishNegativePrompt: event.target.value })} /></label>
      <p className="identity-note">{value.visualPolishMode === "reference-anchor" ? "对齐模式的提示词用于边缘画风与光照融合，不用于重画五官。" : "按脸部目标尺寸细化，裁剪最长边不超过 768；采样蒙版限制重绘区域。只填写脸部细节，不建议重复全身、场景或服装描述。"}</p>
      {!validAnimeStrength(value.animeDenoiseStrength ?? .35) && <p className="identity-error" role="alert">重绘强度必须为 0.15–0.65。</p>}
      {!validVisualAnchorStrength(value.visualAnchorStrength ?? .95) && <p className="identity-error" role="alert">参考脸融合强度必须为 0.3–1。</p>}
      {!ready && <div className="identity-error" role="alert">
        <p>当前无法进行局部重绘。可关闭局部重绘继续生成，或刷新运行状态后重试。</p>
        <button type="button" className="secondary-button" onClick={() => onChange({ ...value, facePolish: false })}>关闭局部重绘</button>
      </div>}
    </>}
  </section>;
}
