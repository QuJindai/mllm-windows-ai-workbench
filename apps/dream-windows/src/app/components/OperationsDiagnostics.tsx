import { useEffect, useState } from "react";
import "./OperationsDiagnostics.css";

type DiskStatus = "ok" | "warning" | "blocked" | "unknown";
type CheckStatus = "ok" | "missing" | "unknown";
type Snapshot = {
  release: string | null;
  buildId: string | null;
  commit: string | null;
  disk: { status: DiskStatus; freeBytes: number | null };
  checks: { id: string; label: string; status: CheckStatus }[];
  pending: { label: string; count: number | null }[];
};

const checkLabels: Record<string, string> = {
  frontend: "前端入口", assets: "前端脚本资源", core: "生成核心", engine: "原生生成引擎",
  wrapper: "生成包装器", registry: "模型注册表", dependencies: "Web 服务依赖",
};
const checkStates = { ok: "已发现", missing: "缺失", unknown: "未知" };
const diskLabels = { ok: "空间充足", warning: "空间偏低", blocked: "已阻止新生成", unknown: "容量未知" };
const diskGuidance = {
  ok: "可用空间不低于 10 GiB。",
  warning: "可用空间低于 10 GiB，请留意后续生成所需空间。",
  blocked: "可用空间低于 2 GiB。请检查空间，手动处理不需要的文件后刷新；历史查看与取消仍可使用。",
  unknown: "无法确认可用空间，请检查磁盘连接与访问权限；未知不等于零，也不代表空间充足。",
};

function object(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function identifier(value: unknown): string | null {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(value)
    && !/(sk-|gh[pousr]_|github_pat_|token|secret|password|bearer)/i.test(value) ? value : null;
}

function parseSnapshot(value: unknown): Snapshot {
  const raw = object(value);
  const disk = object(raw.disk);
  const validBytes = typeof disk.freeBytes === "number" && Number.isSafeInteger(disk.freeBytes) && disk.freeBytes >= 0;
  const status = disk.freeBytes === null ? "unknown" : validBytes
    ? disk.freeBytes as number < 2 * 1024 ** 3 ? "blocked" : disk.freeBytes as number < 10 * 1024 ** 3 ? "warning" : "ok" : null;
  if (raw.schemaVersion !== 1 || raw.service !== "dream-web" || !status || disk.status !== status || !Array.isArray(raw.checks)) {
    throw new Error("Invalid operations response");
  }
  const release = object(raw.release);
  const pending = object(raw.pendingWork);
  return {
    release: identifier(release.release), buildId: identifier(release.buildId),
    commit: typeof release.commit === "string" && /^[a-fA-F0-9]{7,40}$/.test(release.commit) ? release.commit : null,
    disk: { status, freeBytes: validBytes ? disk.freeBytes as number : null },
    checks: raw.checks.slice(0, 32).flatMap((item) => {
      const check = object(item);
      if (typeof check.id !== "string" || !Object.hasOwn(checkLabels, check.id)) return [];
      const checkStatus = check.status === "ok" || check.status === "missing" ? check.status : "unknown";
      return [{ id: check.id, label: checkLabels[check.id], status: checkStatus }];
    }),
    pending: [["ordinary", "普通任务"], ["identity", "人物任务"], ["batches", "人物批次"]].map(([key, label]) => {
      const count = object(pending[key]);
      return { label, count: count.status === "known" && typeof count.pendingCount === "number" && Number.isSafeInteger(count.pendingCount) && count.pendingCount >= 0 ? count.pendingCount : null };
    }),
  };
}

/** Main can mount this directly; enabled=false avoids requests in mock mode. */
export function OperationsDiagnostics({ enabled = true }: { enabled?: boolean }) {
  const [revision, setRevision] = useState(0);
  const [data, setData] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setData(null);
    setFailed(false);
    setLoading(enabled);
    if (!enabled) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch("/api/operations", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Operations unavailable");
        const snapshot = parseSnapshot(await response.json());
        if (!controller.signal.aborted) setData(snapshot);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [enabled, revision]);

  return (
    <section className="surface-card operations-diagnostics" aria-label="运维诊断" aria-busy={loading}>
      <div className="operations-diagnostics__header">
        <h3 className="operations-diagnostics__title">运维诊断</h3>
        {enabled && <button className="secondary-button operations-diagnostics__refresh" type="button" disabled={loading} onClick={() => setRevision((value) => value + 1)}>刷新诊断</button>}
      </div>
      {!enabled ? <p className="operations-diagnostics__note">连接本地服务后可读取运维状态。</p> : <>
        {loading && <p className="operations-diagnostics__message" role="status">正在读取诊断…</p>}
        {failed && <p className="operations-diagnostics__message operations-diagnostics__message--error" role="alert">诊断暂不可用，请检查本地服务连接与版本后重试。</p>}
        {data && <div className="operations-diagnostics__body" aria-live="polite">
          <dl className="operations-diagnostics__metadata">
            <dt>当前发布</dt><dd>{data.release ?? "未提供"}</dd>
            {data.buildId && <><dt>构建标识</dt><dd>{data.buildId}</dd></>}
            {data.commit && <><dt>源码版本</dt><dd>{data.commit}</dd></>}
            <dt>数据盘可用空间</dt><dd aria-label="可用空间">{data.disk.freeBytes === null ? "未知" : `${(data.disk.freeBytes / 1024 ** 3).toFixed(2)} GiB`}</dd>
          </dl>
          <div className="operations-diagnostics__capacity">
            <strong className="operations-diagnostics__badge" data-status={data.disk.status}>{diskLabels[data.disk.status]}</strong>
            <p className="operations-diagnostics__note">{diskGuidance[data.disk.status]}</p>
          </div>
          <div className="operations-diagnostics__groups">
            <div className="operations-diagnostics__group">
              <h4 className="operations-diagnostics__subtitle">安装检查</h4>
              <ul className="operations-diagnostics__list" aria-label="安装检查">{data.checks.map((check) => <li className="operations-diagnostics__check" data-status={check.status} key={check.id}>{check.label}：{checkStates[check.status]}</li>)}</ul>
              <p className="operations-diagnostics__note">安装检查仅确认文件或依赖元数据存在，未执行浏览器或 GPU 生成验证。</p>
            </div>
            <div className="operations-diagnostics__group">
              <h4 className="operations-diagnostics__subtitle">待处理记录</h4>
              <ul className="operations-diagnostics__list" aria-label="待处理记录">{data.pending.map((item) => <li key={item.label}>{item.label}：{item.count ?? "未知"}</li>)}</ul>
              <p className="operations-diagnostics__note">数量来自磁盘记录，可能包含中断任务；人物任务与批次分别统计，不相加。读取失败时显示未知。</p>
            </div>
          </div>
          <p className="operations-diagnostics__footer">重启后请查看历史与批次记录，确认已完成结果，再手动继续未完成任务。诊断不会自动恢复生成、删除文件或终止进程。</p>
        </div>}
      </>}
    </section>
  );
}
