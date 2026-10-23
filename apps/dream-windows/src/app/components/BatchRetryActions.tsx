import { useRef, useState } from "react";
import { readBatchRetryOperation, reserveBatchRetryOperation } from "../../providers/identity-api";
import type { BatchRetryPayload } from "../../providers/identity-api";

export type { BatchRetryPayload } from "../../providers/identity-api";
export type BatchRetryMode = BatchRetryPayload["mode"];
type BatchState = "queued" | "preparing" | "sampling" | "complete" | "failed" | "cancelled";
export type BatchRetrySummary = {
  id: string;
  state: BatchState;
  items: Array<{ state: BatchState; resultDeleted?: boolean }>;
  parentBatchId?: string | null;
  originalItemIndices?: number[] | null;
};
export type BatchRetryActionsProps = {
  batch: BatchRetrySummary;
  disabled?: boolean;
  onRetry: (batchId: string, payload: BatchRetryPayload) => Promise<unknown>;
};

/** onRetry submits the payload and selects/polls the returned child in the host page. */
export function BatchRetryActions(props: BatchRetryActionsProps) {
  return <RetryControls key={props.batch.id} {...props} />;
}

function RetryControls({ batch, onRetry, disabled = false }: BatchRetryActionsProps) {
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stored, setStored] = useState(() => {
    try { return { operation: readBatchRetryOperation(batch.id), error: null as string | null }; }
    catch (failure) { return { operation: null, error: failure instanceof Error ? failure.message : "无法读取重试记录，请恢复会话存储后刷新" }; }
  });
  const terminal = ["complete", "failed", "cancelled"].includes(batch.state);
  const failed = batch.items.filter(item => item.state === "failed").length;
  const unfinished = batch.items.filter(item => item.state !== "complete").length;
  // A saved operation may need readback even when the workspace has discovered
  // its active child. The host still serializes this with other pending writes.
  const blocked = (disabled && !stored.operation) || !terminal || pending || submitted || !!stored.error;

  async function retry(mode: BatchRetryMode) {
    if (busy.current || blocked || !(mode === "failed" ? failed : unfinished)) return;
    busy.current = true;
    setPending(true);
    setError(null);
    try {
      // Re-read synchronously as well as disabling the other mode: stale
      // component instances must not allocate another key for the same parent.
      const operation = reserveBatchRetryOperation(batch.id, mode);
      setStored({ operation, error: null });
      await onRetry(batch.id, { mode: operation.mode, idempotencyKey: operation.idempotencyKey });
      setSubmitted(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "批次重试失败，请重试");
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return <section aria-label="批次重试" aria-busy={pending}>
    {batch.parentBatchId && <p className="identity-note">来源批次：{batch.parentBatchId}</p>}
    {batch.originalItemIndices && <p className="identity-note">原批次图片：{batch.originalItemIndices.map(index => index + 1).join("、")}</p>}
    <div className="identity-actions" role="group" aria-label="重试操作">
      <button className="secondary-button" type="button" disabled={blocked || failed === 0 || !!stored.operation && stored.operation.mode !== "failed"} onClick={() => void retry("failed")}>重试失败项（{failed}）</button>
      <button className="secondary-button" type="button" disabled={blocked || unfinished === 0 || !!stored.operation && stored.operation.mode !== "unfinished"} onClick={() => void retry("unfinished")}>继续未完成项（{unfinished}）</button>
    </div>
    {!terminal && <p className="identity-note">等待原批次结束或取消后再重试。</p>}
    <p className="identity-note">使用原批次的固定参数创建新批次，保留已完成图片。</p>
    {stored.operation && <p className="identity-note">此父批次已锁定为{stored.operation.mode === "failed" ? "重试失败项" : "继续未完成项"}；再次点击同一操作恢复或打开子批次，不创建新请求编号。后续重试请从子批次发起。</p>}
    <p role="status">{pending ? "正在提交重试…" : submitted ? "重试已提交，请查看子批次。" : ""}</p>
    {(error || stored.error) && <p role="alert" className="identity-error">{error || stored.error}</p>}
  </section>;
}
