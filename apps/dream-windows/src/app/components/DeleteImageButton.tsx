import { useContext, useState } from "react";
import { DreamProviderContext } from "../providers";
import { identityApi } from "../../providers/identity-api";
import { useImageDeletion } from "../image-deletion-state";
import "./DeleteImageButton.css";

export function DeleteImageButton({ id, onDelete, disabled = false, recordOnly = false, batchCount }: { id: string; onDelete: (id: string) => Promise<void>; disabled?: boolean; recordOnly?: boolean; batchCount?: number }) {
  const [confirming, setConfirming] = useState(false);
  const provider = useContext(DreamProviderContext);
  const { busy, error, deleted, remove: deleteImage } = useImageDeletion(provider ?? identityApi, id);
  async function remove() {
    if (!disabled && await deleteImage(onDelete)) setConfirming(false);
  }
  const batch = batchCount !== undefined;
  if (deleted) return <p role="status">{batch ? "批次已删除" : recordOnly ? "记录已删除" : "图片已删除"}</p>;
  const label = batch ? "删除批次" : recordOnly ? "删除记录" : "删除图片";
  return <div className="image-delete-control">
    <button type="button" className="danger-button" aria-label={`${label} ${id}`} disabled={disabled || busy} onClick={() => setConfirming(true)}>{busy ? "正在删除…" : label}</button>
    {confirming && <section role="dialog" aria-label={batch ? "删除人物批次" : recordOnly ? "删除人物任务记录" : "删除生成图片"} className="surface-card image-delete-confirm">
      <p>{batch ? `删除整个批次及其中 ${batchCount} 项任务、生成图、修脸前原图和阶段图片？人物档案与参考照片保留。` : recordOnly ? "删除这条人物任务记录？保留人物档案和参考照片。" : "删除这张生成图、对应的修脸前原图及历史记录？不删除人物档案和参考照片。"}</p>
      {!recordOnly && <p className="muted-copy">文件移入本机删除暂存区，不会立即永久擦除。</p>}
      <div className="image-delete-actions"><button type="button" className="secondary-button" disabled={busy} onClick={() => setConfirming(false)}>取消删除</button>
        <button type="button" className="danger-button" disabled={disabled || busy} onClick={() => void remove()}>{busy ? "正在删除…" : batch ? "确认删除批次" : recordOnly ? "确认删除记录" : "确认删除图片"}</button></div>
    </section>}
    {error && <p role="alert" className="error-panel">{error}</p>}
  </div>;
}
