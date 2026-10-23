import { useState } from "react";
import type { IdentityProfile, ReferenceKind } from "../../../domain/identity";

type Props = {
  profiles: IdentityProfile[]; profileId: string; profile: IdentityProfile | null;
  referenceKind?: ReferenceKind;
  disabled: boolean; selectionDisabled: boolean; canCreate: boolean;
  onSelect: (id: string) => void; onNew: () => void; onCreate: (name: string) => void;
  onRename: (name: string) => void; onArchive: () => Promise<boolean | undefined>;
};
const labels = { preparing: "准备中", ready: "可使用", failed: "准备失败", archived: "已撤下" };

export function ProfileLibrary({ profiles, profileId, profile, referenceKind = "faceid", disabled, selectionDisabled, canCreate, onSelect, onNew, onCreate, onRename, onArchive }: Props) {
  const [name, setName] = useState(profile?.name ?? "");
  const [confirming, setConfirming] = useState(false);
  const validName = !!name.trim();
  const visual = (profile?.referenceKind ?? referenceKind) === "visual";
  return <section className="identity-profile-library" aria-label="人物档案库">
    <div className="identity-profile-heading"><h2>人物档案</h2>
      <button className="primary-button" type="button" disabled={disabled} onClick={() => { setName(""); setConfirming(false); onNew(); }}>新建人物</button>
    </div>
    <label>选择人物档案<select value={profileId} disabled={selectionDisabled} onChange={(event) => onSelect(event.target.value)}>
      <option value="">临时参考照 / 创建新档案</option>
      {profiles.filter((item) => item.state !== "archived").map((item) => <option key={item.id} value={item.id}>{item.name} · {item.referenceKind === "visual" ? "视觉参考" : "FaceID"} · {labels[item.state]}</option>)}
      {profileId && !profiles.some((item) => item.id === profileId && item.state !== "archived") && <option value={profileId}>原人物档案不可用</option>}
    </select></label>
    {profile && <div aria-label="人物档案状态" role="status">{labels[profile.state]}{profile.state === "preparing" ? ` · 正在排队准备本地${profile.referenceKind === "visual" ? "视觉参考" : "身份"}特征，请稍候。` : ""}</div>}
    {profile?.error && <p className="identity-error" role="alert">{profile.error}</p>}
    <label>档案名称<input type="text" maxLength={120} value={name} disabled={disabled} onChange={(event) => setName(event.target.value)} placeholder={visual ? "例如：示例人物-动漫-视觉" : "例如：示例人物-素颜"} /></label>
    <div className="identity-actions">
      {!profileId ? <button className="secondary-button" type="button" disabled={disabled || !canCreate || !validName} onClick={() => onCreate(name)}>创建人物档案</button>
        : <><button className="secondary-button" type="button" disabled={disabled || !profile || profile.state === "archived" || !validName} onClick={() => onRename(name)}>重命名人物档案</button>
          <button className="danger-button" type="button" disabled={disabled || !profile || profile.state === "archived"} onClick={() => setConfirming(true)}>撤下人物档案</button></>}
    </div>
    {!profileId && <div className="identity-create-guide" aria-label="新人物建档步骤">
      <strong>上传参考照 → 确认人脸 → 命名并创建</strong>
      <p className="identity-note">{canCreate ? "人脸已选定，填写名称后点击“创建人物档案”。" : visual ? "先在下方上传动漫参考图或选择已有参考照，再确认人脸。" : "先在下方上传清晰照片或选择参考照，再确认人脸。"}建档完成后显示“可使用”，以后无需重复上传。不会覆盖已有档案。</p>
      {visual && <p className="identity-note">将创建视觉参考档案，缓存 CLIP 视觉特征，不建立 FaceID 生物身份。已有 FaceID 参考照也可用于新建视觉档案。</p>}
    </div>}
    {profileId && <p className="identity-note">档案绑定原参考照与选定人脸。点击“新建人物”可为另一张图片独立建档；生成结果不会替换{visual ? "视觉参考" : "身份"}特征。</p>}
    {confirming && <div className="identity-confirm" role="dialog" aria-label="确认撤下人物档案">
      <p>将“{profile?.name}”撤下为可恢复归档，不删除参考照或历史结果。活跃任务使用的档案暂不能撤下。</p>
      <div className="identity-actions"><button className="secondary-button" type="button" disabled={disabled} onClick={() => setConfirming(false)}>暂不撤下</button>
        <button className="danger-button" type="button" disabled={disabled} onClick={() => { void onArchive().then((ok) => { if (ok) setConfirming(false); }); }}>确认撤下</button></div>
    </div>}
  </section>;
}
