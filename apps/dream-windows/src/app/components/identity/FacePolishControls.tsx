import { useId } from "react";
import { validAnimeStrength, validFaceRestoreStrength } from "../../../domain/identity";
import type { AnimeProfile, IdentityRequest, IdentityStatus } from "../../../domain/identity";

type Options = Pick<IdentityRequest, "facePolish" | "faceRestoreStrength" | "animeProfileId" | "animeDenoiseStrength">;
export function FacePolishControls({ value, capability, animeCapability, animeProfiles = [], allowAnime = false, onChange }: {
  value: Options; capability: IdentityStatus["facePolish"]; onChange: (value: Options) => void;
  animeCapability?: IdentityStatus["animePolish"]; animeProfiles?: AnimeProfile[]; allowAnime?: boolean;
}) {
  const hint = useId(), availability = useId();
  const anime = animeProfiles.find(p => p.id === value.animeProfileId && p.state === "ready");
  const isAnime = !!value.animeProfileId;
  const activeCapability = isAnime ? animeCapability : capability;
  const ready = isAnime ? allowAnime && !!anime && animeCapability?.ready === true : capability?.ready === true;
  return <section className="identity-face-polish-controls" aria-label="可选生成后修脸">
    {(allowAnime || isAnime) && <>
      <label>修脸参考<select value={value.animeProfileId ?? ""} onChange={event => onChange({...value,animeProfileId:event.target.value || undefined,animeDenoiseStrength:.35})}>
        <option value="">原参考人物 · 真人身份回贴</option>
        {animeProfiles.filter(p=>p.state==="ready").map(p=><option key={p.id} value={p.id}>{p.name} · 动漫局部重绘</option>)}
        {isAnime && !anime && <option value={value.animeProfileId!}>原动漫档案不可用或不匹配</option>}
      </select></label>
      {anime && <img className="identity-anime-thumb" src={anime.imageUrl} alt={`动漫修脸参考：${anime.name}`} />}
    </>}
    <label className="identity-polish-checkbox">
      <input type="checkbox" checked={value.facePolish} disabled={!ready && !value.facePolish}
        aria-describedby={`${hint} ${availability}`}
        onChange={(event) => onChange({ ...value, facePolish: event.target.checked })} />
      生成后修脸（可选）
    </label>
    <p id={hint} className="identity-note">{isAnime ? "按动漫参考局部重绘脸部，保留脸外画面；不使用真人换脸或 GFPGAN，不保证精确复制形象。修脸仍为可选，失败时保留原图。" : "默认关闭。生成后先进行身份回贴，再进行面部细节修复；保留生成原图与修脸结果，修脸失败时保留原图并显示原因。"}</p>
    <p id={availability} className="identity-note">{ready ? activeCapability?.message || "修脸可用" : isAnime && !anime ? "请选择当前人物已就绪的动漫档案。" : activeCapability?.message || "服务未报告修脸能力，当前不可用。"}</p>
    {!ready && value.facePolish && <p className="identity-error">当前无法修脸。请关闭“生成后修脸”以继续生成，或刷新运行状态后重试。</p>}
    {value.facePolish && isAnime && <>
      <label>动漫局部重绘强度<input type="number" min={.15} max={.65} step={.05} disabled={!ready}
        value={Number.isFinite(value.animeDenoiseStrength ?? .35) ? value.animeDenoiseStrength ?? .35 : ""}
        onChange={event=>onChange({...value,animeDenoiseStrength:event.target.value==="" ? NaN : Number(event.target.value)})}/></label>
      <p className="identity-note">0.15–0.65，默认 0.35。越高改变越大；先用默认值观察前后对比。</p>
      {!validAnimeStrength(value.animeDenoiseStrength ?? .35) && <p role="alert">动漫局部重绘强度必须为 0.15–0.65。</p>}
    </>}
    {value.facePolish && !isAnime && <>
      <label>面部细节修复强度<input type="number" min={0} max={1} step={0.01}
        disabled={!ready} value={Number.isFinite(value.faceRestoreStrength) ? value.faceRestoreStrength : ""}
        onChange={(event) => onChange({ ...value, faceRestoreStrength: event.target.value === "" ? NaN : Number(event.target.value) })} /></label>
      <p className="identity-note">0–1，默认 1。控制面部细节修复程度；身份回贴仍会执行。</p>
      {!validFaceRestoreStrength(value.faceRestoreStrength) && <p className="identity-error">面部细节修复强度必须为 0–1。</p>}
    </>}
  </section>;
}
