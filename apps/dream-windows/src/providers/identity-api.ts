import type { AnimeProfile, AnimeProfileImport, IdentityBatch, IdentityBatchRequest, IdentityJob, IdentityProfile, IdentityReference, IdentityRequest, IdentityStatus, ReferenceKind } from "../domain/identity";
import { identityReferenceKind, validVisualPolishResult } from "../domain/identity";

function decodeStatus(status: IdentityStatus): IdentityStatus {
  const capability: unknown = status.visualPolish;
  if (capability === undefined) return status;
  if (capability && typeof capability === "object" && !Array.isArray(capability)
    && "ready" in capability && typeof capability.ready === "boolean"
    && "message" in capability && typeof capability.message === "string") {
    if (("referenceAnchorReady" in capability && capability.referenceAnchorReady !== undefined && typeof capability.referenceAnchorReady !== "boolean")
      || ("referenceAnchorMessage" in capability && capability.referenceAnchorMessage !== undefined && typeof capability.referenceAnchorMessage !== "string")) {
      return { ...status, visualPolish: { ...status.visualPolish!, referenceAnchorReady: false,
        referenceAnchorMessage: "服务返回的参考脸对齐能力无效，当前不可用。" } };
    }
    return status;
  }
  return { ...status, visualPolish: { ready: false, message: "服务返回的视觉重绘能力无效，当前不可用。" } };
}

function decodeVisualJob(job: IdentityJob): IdentityJob {
  if (!job.result || identityReferenceKind(job.request.modelId) !== "visual") return job;
  const polish: unknown = job.result.metadata.facePolish;
  // Recovered generation completion does not prove that the requested polish ran.
  // Keep the result and frozen request, but never promote absent evidence to success.
  if ((polish == null && (job.state !== "complete" || job.request.facePolish !== true))
    || validVisualPolishResult(polish, job.request, job.id)) return job;
  return { ...job, result: { ...job.result, metadata: { ...job.result.metadata, facePolish: undefined,
    unverifiedFacePolish: polish, facePolishValidationError: "视觉重绘记录无效，未确认重绘完成；生成图像仍可查看。" } } };
}

function decodeVisualBatch(batch: IdentityBatch): IdentityBatch {
  return { ...batch, items: batch.items.map(decodeVisualJob) };
}

function errorMessage(body: unknown): string | undefined {
  if (typeof body === "string") return body;
  if (Array.isArray(body)) return body.map(errorMessage).filter(Boolean).join("；");
  if (body && typeof body === "object") {
    const error = body as Record<string, unknown>;
    const messages = [
      errorMessage(error.message ?? error.msg ?? error.error),
      errorMessage(error.detail ?? error.errors),
    ].filter(Boolean);
    return [...new Set(messages)].join("；") || undefined;
  }
}

async function request<T>(path: string, init: RequestInit = {}, prefix = "/api/identity"): Promise<T> {
  const response = await fetch(`${prefix}${path}`, {
    ...init, credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(errorMessage(body) || `人物服务请求失败（HTTP ${response.status}）`);
  if (body === null) throw new Error("人物服务未返回有效数据");
  return body as T;
}

export type BatchRetryPayload = { mode: "failed" | "unfinished"; idempotencyKey: string };
type BatchRetryOperation = BatchRetryPayload & { childId?: string };
const retryStorageKey = (id: string) => `dream.batchRetry:${id}`;
const validRetryKey = (key: unknown): key is string => typeof key === "string" && !!key.trim() && key.length <= 128;

/** A parent owns ONE operation, not one key per mode. Never discard an uncertain acceptance. */
export function readBatchRetryOperation(id: string): BatchRetryOperation | null {
  const raw = sessionStorage.getItem(retryStorageKey(id));
  if (raw !== null) {
    const value = JSON.parse(raw) as Partial<BatchRetryOperation> | null;
    if (!value || (value.mode !== "failed" && value.mode !== "unfinished") || !validRetryKey(value.idempotencyKey)
      || (value.childId !== undefined && (typeof value.childId !== "string" || !value.childId || value.childId === id))) {
      throw new Error("重试记录损坏，请检查批次历史；为避免重复生成，不创建新请求编号。");
    }
    return value as BatchRetryOperation;
  }
  // Upgrade pre-fix sessions without silently replacing a key whose response was lost.
  const legacy = (["failed", "unfinished"] as const).flatMap(mode => {
    const idempotencyKey = sessionStorage.getItem(`${retryStorageKey(id)}:${mode}`);
    return idempotencyKey === null ? [] : [{ mode, idempotencyKey }];
  });
  if (legacy.length > 1 || legacy.some(value => !validRetryKey(value.idempotencyKey))) {
    throw new Error("存在多个或无效的旧重试记录，请在批次历史核对已有子批次；不创建新请求编号。");
  }
  return legacy[0] ?? null;
}

export function reserveBatchRetryOperation(id: string, mode: BatchRetryPayload["mode"], key?: string): BatchRetryOperation {
  const previous = readBatchRetryOperation(id);
  if (previous && (previous.mode !== mode || key !== undefined && previous.idempotencyKey !== key)) {
    throw new Error("此父批次已有重试操作，请先恢复原模式和请求编号对应的子批次。");
  }
  const operation = previous ?? { mode, idempotencyKey: key ?? crypto.randomUUID() };
  if (!validRetryKey(operation.idempotencyKey)) throw new Error("重试请求编号无效");
  // Persist BEFORE the HTTP boundary; failures must not leave an untracked POST.
  sessionStorage.setItem(retryStorageKey(id), JSON.stringify(operation));
  return operation;
}

export const identityApi = {
  deleteBatch: async (id: string) => {
    const response = await request<{ deleted: string; deletedJobIds: string[] }>(`/batches/${encodeURIComponent(id)}`, { method: "DELETE" });
    const ids = response?.deletedJobIds;
    if (response?.deleted !== id || !Array.isArray(ids) || !ids.length || ids.length > 16
      || ids.some(value => typeof value !== "string" || !value.trim() || value === id) || new Set(ids).size !== ids.length) {
      throw new Error("整批删除未得到完整确认，请刷新后重试");
    }
    return response;
  },
  animeProfiles: (signal?: AbortSignal) => request<AnimeProfile[]>("/anime-profiles", {signal}),
  createAnimeProfile: (body: {name: string; profileId: string; jobId: string}) => request<AnimeProfile>("/anime-profiles", {method:"POST",body:JSON.stringify(body)}),
  importAnimeProfile: (body: AnimeProfileImport) => request<AnimeProfile>("/anime-profiles/import", {method:"POST",body:JSON.stringify(body)}),
  deleteResult: async (id: string): Promise<void> => {
    const response = await request<{ deleted: string }>(`/${encodeURIComponent(id)}`, { method: "DELETE" }, "/api/history");
    if (response.deleted !== id) throw new Error("删除未得到确认，请刷新后重试");
  },
  deleteJob: async (id: string): Promise<void> => {
    const response = await request<{ deleted: string }>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (response.deleted !== id) throw new Error("删除未得到确认，请刷新后重试");
  },
  status: (signal?: AbortSignal) => request<IdentityStatus>("/status", { signal }).then(decodeStatus),
  references: (signal?: AbortSignal) => request<IdentityReference[]>("/references", { signal }),
  uploadReference: (name: string, imageBase64: string, referenceKind?: ReferenceKind) => request<IdentityReference>("/references", {
    method: "POST", body: JSON.stringify({ name, imageBase64, ...(referenceKind ? { referenceKind } : {}) }),
  }),
  generate: (body: IdentityRequest) => request<IdentityJob>("/generate", { method: "POST", body: JSON.stringify(body) }).then(decodeVisualJob),
  jobs: (signal?: AbortSignal) => request<IdentityJob[]>("/jobs", { signal }).then(jobs => jobs.map(decodeVisualJob)),
  job: (id: string, signal?: AbortSignal) => request<IdentityJob>(`/jobs/${encodeURIComponent(id)}`, { signal }).then(decodeVisualJob),
  cancel: (id: string) => request<IdentityJob>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }).then(decodeVisualJob),
  profiles: (signal?: AbortSignal) => request<IdentityProfile[]>("/profiles", { signal }),
  profile: (id: string, signal?: AbortSignal) => request<IdentityProfile>(`/profiles/${encodeURIComponent(id)}`, { signal }),
  createProfile: (body: { name: string; referenceId: string; faceIndex: number; referenceKind?: ReferenceKind }) => request<IdentityProfile>("/profiles", { method: "POST", body: JSON.stringify(body) }),
  renameProfile: (id: string, name: string) => request<IdentityProfile>(`/profiles/${encodeURIComponent(id)}/rename`, { method: "POST", body: JSON.stringify({ name }) }),
  archiveProfile: (id: string) => request<IdentityProfile>(`/profiles/${encodeURIComponent(id)}/archive`, { method: "POST" }),
  savePreset: (id: string, jobId: string) => request<IdentityProfile>(`/profiles/${encodeURIComponent(id)}/preset`, { method: "POST", body: JSON.stringify({ jobId }) }),
  batches: (signal?: AbortSignal) => request<IdentityBatch[]>("/batches", { signal }).then(batches => batches.map(decodeVisualBatch)),
  batch: (id: string, signal?: AbortSignal) => request<IdentityBatch>(`/batches/${encodeURIComponent(id)}`, { signal }).then(decodeVisualBatch),
  createBatch: (body: IdentityBatchRequest) => request<IdentityBatch>("/batches", { method: "POST", body: JSON.stringify(body) }).then(decodeVisualBatch),
  cancelBatch: (id: string) => request<IdentityBatch>(`/batches/${encodeURIComponent(id)}/cancel`, { method: "POST" }).then(decodeVisualBatch),
  retryBatch: async (id: string, body: BatchRetryPayload): Promise<IdentityBatch> => {
    const operation = reserveBatchRetryOperation(id, body.mode, body.idempotencyKey);
    // A confirmed receipt is read-only. An uncertain receipt is reconciled by
    // replaying exactly the original operation against the server's durable key.
    const value = operation.childId ? await identityApi.batch(operation.childId)
      : await request<IdentityBatch>(`/batches/${encodeURIComponent(id)}/retry`, {
        method: "POST", body: JSON.stringify({ mode: operation.mode, idempotencyKey: operation.idempotencyKey }),
      }).then(decodeVisualBatch);
    if (!value.id || value.id === id || value.parentBatchId !== id || operation.childId && value.id !== operation.childId) {
      throw new Error("重试子批次来源未确认，保留原请求编号，请检查批次历史。");
    }
    sessionStorage.setItem(retryStorageKey(id), JSON.stringify({ ...operation, childId: value.id }));
    return value;
  },
};

export function readReferenceFile(file: File): Promise<string> {
  if (file.size > 10 * 1024 * 1024) return Promise.reject(new Error("参考照不能超过 10 MiB"));
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return Promise.reject(new Error("请选择 PNG、JPEG 或 WebP 图片"));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取参考照，请重新选择"));
    reader.onabort = () => reject(new Error("参考照读取已中止"));
    reader.onload = () => {
      const value = reader.result;
      if (typeof value !== "string" || !value.includes(",")) reject(new Error("参考照读取失败"));
      else resolve(value.slice(value.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}
