import type { HQAsset, HQCatalog, HQCreateRequest, HQIdentityOptions, HQJob, HQParameters, HQRole, HQStatus } from "../domain/hq-tryon";
import { hqActive, hqError, hqExecutionBasis, validHQParameters } from "../domain/hq-tryon";

const root = "/api/hq";
const validId = (id: unknown): id is string => typeof id === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(id);
const cleanParameters = (p: HQParameters): HQParameters => ({ seed: p.seed, width: p.width, height: p.height, steps: p.steps });
const sha256Hex = async (bytes: BufferSource) => Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), n => n.toString(16).padStart(2, "0")).join("");
function identifier(id: string) { if (!validId(id)) throw new Error("HQ 编号无效"); return encodeURIComponent(id); }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(root + path, { ...init, credentials: "same-origin", redirect: "error", cache: "no-store",
    headers: { "Content-Type": "application/json", ...init.headers } });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(hqError(data?.error) || hqError(data?.detail) || `HQ 请求失败（HTTP ${response.status}）`);
  if (!data || typeof data !== "object") throw new Error("HQ 服务未返回有效数据");
  return data as T;
}
function decodeJob(data: HQJob | { job: HQJob }): HQJob {
  const job = "job" in data ? data.job : data;
  if (!job || !validId(job.id) || !["queued", "running", "succeeded", "failed", "cancelled"].includes(job.state)) throw new Error("HQ 任务状态无效");
  return { ...job, inputs: Array.isArray(job.inputs) ? job.inputs : [] };
}
export const hqApi = {
  status: (signal?: AbortSignal) => request<HQStatus>("/status", { signal }),
  catalog: async (kind: HQRole, q = "", category = "", page = 0, signal?: AbortSignal): Promise<HQCatalog> => {
    const data = await request<HQCatalog>("/catalog?" + new URLSearchParams({ kind, q, category, page: String(page), limit: "24" }), { signal });
    if (!Array.isArray(data.items) || !Number.isFinite(data.total)) throw new Error("HQ 图库格式无效");
    return { ...data, categories: Array.isArray(data.categories) ? data.categories : [] };
  },
  jobs: async (signal?: AbortSignal) => {
    const data = await request<{ jobs: HQJob[] }>("/jobs", { signal });
    if (!Array.isArray(data.jobs)) throw new Error("HQ 任务列表格式无效");
    return data.jobs.map(decodeJob);
  },
  job: async (id: string, signal?: AbortSignal) => {
    const job = decodeJob(await request<HQJob>(`/jobs/${identifier(id)}`, { signal }));
    if (job.id !== id) throw new Error("HQ 任务编号不匹配");
    return job;
  },
  create: (body: HQCreateRequest) => request<HQJob>("/jobs", { method: "POST", body: JSON.stringify(body) }).then(decodeJob),
  cancel: async (id: string) => {
    const job = decodeJob(await request<HQJob>(`/jobs/${identifier(id)}/cancel`, { method: "POST" }));
    if (job.id !== id) throw new Error("HQ 取消回执编号不匹配");
    return job;
  },
  assetUrl: (kind: HQRole, id: string, thumbnail = false) => root + "/asset?" + new URLSearchParams({ kind, id, ...(thumbnail ? { thumbnail: "1" } : {}) }),
  inputUrl: (id: string, role: HQRole) => `${root}/jobs/${identifier(id)}/inputs/${role}`,
  resultUrl: (id: string) => `${root}/jobs/${identifier(id)}/result`,
  result: async (job: HQJob, signal?: AbortSignal): Promise<Blob> => {
    const expected = job.result?.sha256 || job.output?.sha256;
    if (!/^[a-f0-9]{64}$/.test(expected || "")) throw new Error("缺少成片 SHA-256，无法校验原图");
    const response = await fetch(hqApi.resultUrl(job.id), { credentials: "same-origin", redirect: "error", cache: "no-store", signal });
    if (!response.ok) throw new Error(`成片读取失败（HTTP ${response.status}）`);
    const header = response.headers.get("x-content-sha256");
    if (response.headers.get("content-type")?.split(";")[0] !== "image/png" || header && header !== expected) throw new Error("成片校验信息不一致");
    const blob = await response.blob();
    if (!blob.size || blob.size > 32 * 1024 * 1024) throw new Error("成片大小无效");
    const actual = await sha256Hex(await blob.arrayBuffer());
    if (actual !== expected) throw new Error("成片 SHA-256 校验失败，已阻止预览和下载");
    return blob;
  },
};

// Only selection IDs, parameters and receipts are persisted. No pixels or authorization material.
export interface HQOperation { fingerprint: string; idempotencyKey: string; jobId?: string; retryOf?: string; delivery: "prepared" | "unknown" | "submitted" }
export interface HQDraft extends HQIdentityOptions { selection: Partial<Record<HQRole, HQAsset>>; parameters: HQParameters; activeJobId?: string }
// Unqualified v1 receipts belong to the earlier execution basis. Never upgrade
// them by filling defaults; verified current server jobs can restore their keys.
const operationsKey = "dream.hq.operations.v2", draftKey = "dream.hq.draft.v1";
export const hqFingerprint = (body: Omit<HQCreateRequest, "idempotencyKey">) => JSON.stringify([hqExecutionBasis, body.personId, body.garmentId, body.poseId, body.parameters.seed, body.parameters.width, body.parameters.height, body.parameters.steps, body.profileId || null, body.facePolish ?? false, body.faceRestoreStrength ?? 0.35]);
function cleanIdentity(value: HQIdentityOptions): HQIdentityOptions {
  return { profileId: validId(value.profileId) ? value.profileId : null, facePolish: value.facePolish === true,
    faceRestoreStrength: typeof value.faceRestoreStrength === "number" && Number.isFinite(value.faceRestoreStrength) && value.faceRestoreStrength >= 0 && value.faceRestoreStrength <= 1 ? value.faceRestoreStrength : 0.35 };
}
const validKey = (key: unknown): key is string => typeof key === "string" && /^[A-Za-z0-9._:-]{8,128}$/.test(key);
function validFingerprint(value: unknown): value is string {
  if (typeof value !== "string" || value.length >= 768) return false;
  try {
    const fields = JSON.parse(value);
    return Array.isArray(fields) && fields.length === 11 && fields[0] === hqExecutionBasis && fields.slice(1, 4).every(validId)
      && validHQParameters({ seed: fields[4], width: fields[5], height: fields[6], steps: fields[7] })
      && (fields[8] === null || validId(fields[8])) && typeof fields[9] === "boolean"
      && typeof fields[10] === "number" && fields[10] >= 0 && fields[10] <= 1;
  } catch { return false; }
}
function storedOperations(storage: Storage): HQOperation[] {
  const values: unknown = JSON.parse(storage.getItem(operationsKey) || "[]");
  if (!Array.isArray(values)) return [];
  return values.filter(r => r && validFingerprint(r.fingerprint) && validKey(r.idempotencyKey)
    && (!r.jobId || validId(r.jobId)) && (r.retryOf === undefined || validId(r.retryOf)) && ["prepared", "unknown", "submitted"].includes(r.delivery))
    .map(({ fingerprint, idempotencyKey, jobId, retryOf, delivery }) => ({ fingerprint: JSON.stringify(JSON.parse(fingerprint)), idempotencyKey, jobId, retryOf, delivery }));
}
export function readHQOperations(): HQOperation[] {
  try { return storedOperations(localStorage); } catch { return []; /* Writes still fail closed before POST. */ }
}
function persistHQOperation(operation: HQOperation, expectedKey: string) {
  const receipts = storedOperations(localStorage), previous = receipts.find(value => value.fingerprint === operation.fingerprint);
  if (previous ? previous.idempotencyKey !== expectedKey : expectedKey !== operation.idempotencyKey) throw new Error("请求回执已更新，请先刷新核对当前尝试");
  const values = receipts.filter(value => value.fingerprint !== operation.fingerprint);
  const { fingerprint, idempotencyKey, jobId, retryOf, delivery } = operation;
  if (!validFingerprint(fingerprint) || !validKey(idempotencyKey) || jobId && !validId(jobId) || retryOf !== undefined && !validId(retryOf)) throw new Error("HQ 请求回执无效");
  localStorage.setItem(operationsKey, JSON.stringify([...values, { fingerprint, idempotencyKey, jobId, retryOf, delivery }]));
}
export const saveHQOperation = (operation: HQOperation) => persistHQOperation(operation, operation.idempotencyKey);
const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
function hasCurrentBasis(job: HQJob) {
  const evidence = [job.pipeline, record(job.audit).pipeline, record(job.localAudit).pipeline,
    ...[job.result?.metadata, job.output?.metadata, job.identityResult?.metadata].map(metadata => record(record(metadata).hq).pipeline)]
    .filter(value => value !== undefined && value !== null);
  return evidence.length > 0 && evidence.every(value => value === hqExecutionBasis);
}
const currentExecution = (job: HQJob) => validId(job.identityJobId) && hasCurrentBasis(job);
function jobSettingsFingerprint(job: HQJob): string | null {
  if (!job.parameters || !validHQParameters(job.parameters)) return null;
  const personId = job.requestedInputIds?.person || job.inputs.find(input => input.role === "person")?.id;
  const garmentId = job.requestedInputIds?.garment || job.inputs.find(input => input.role === "garment")?.id;
  const poseId = job.requestedInputIds?.pose || job.inputs.find(input => input.role === "pose")?.id;
  return validId(personId) && validId(garmentId) && validId(poseId) ? hqFingerprint({ personId, garmentId, poseId, parameters: job.parameters, ...cleanIdentity(job) }) : null;
}
export const hqJobFingerprint = (job: HQJob): string | null => currentExecution(job) ? jobSettingsFingerprint(job) : null;

// The service emits ISO timestamps with an explicit offset and up to six fractional digits.
function createdMicros(job: HQJob): number {
  const parts = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(job.createdAt ?? "");
  if (!parts) return NaN;
  const [, clock, fraction = "", zone] = parts;
  const calendar = Date.parse(clock + "Z");
  if (!Number.isFinite(calendar) || new Date(calendar).toISOString().slice(0, 19) !== clock) return NaN;
  const micros = Date.parse(clock + zone) * 1000 + Number(fraction.padEnd(6, "0"));
  return Number.isSafeInteger(micros) ? micros : NaN;
}

function confirmedSuccessor(receipt: HQOperation, jobs: HQJob[]) {
  if (!receipt.retryOf || receipt.delivery !== "submitted" || !receipt.jobId) return;
  const current = jobs.find(job => job.id === receipt.jobId && job.idempotencyKey === receipt.idempotencyKey);
  if (!current || hqActive(current) || hqJobFingerprint(current) !== receipt.fingerprint) return;
  const currentTime = createdMicros(current);
  if (!Number.isFinite(currentTime)) return;

  let latestTime = currentTime;
  let latest: HQJob | undefined;
  for (const job of jobs) {
    if (job.id === current.id || job.id === receipt.retryOf || job.idempotencyKey === receipt.idempotencyKey || !validKey(job.idempotencyKey)) continue;
    if (hqJobFingerprint(job) !== receipt.fingerprint) continue;
    const time = createdMicros(job);
    if (time > latestTime) { latest = job; latestTime = time; }
    else if (time === latestTime && latest?.id !== job.id) latest = undefined;
  }
  return latest;
}

export function reconcileHQOperations(jobs: HQJob[], onSuccessor?: (previousId: string, nextId: string) => void): HQOperation[] {
  const receipts = storedOperations(localStorage), matched = new Set<string>();
  // Resolve a completed attempt before scanning the list, regardless of response order.
  for (const receipt of receipts) {
    const next = confirmedSuccessor(receipt, jobs);
    if (!next?.idempotencyKey || !receipt.jobId) continue;
    onSuccessor?.(receipt.jobId, next.id);
    receipt.retryOf = receipt.jobId;
    receipt.jobId = next.id;
    receipt.idempotencyKey = next.idempotencyKey;
  }
  for (const job of jobs) {
    if (!currentExecution(job) || !validKey(job.idempotencyKey)) continue;
    const prior = receipts.find(row => row.idempotencyKey === job.idempotencyKey);
    const fingerprint = hqJobFingerprint(job) || prior?.fingerprint;
    if (!fingerprint || matched.has(fingerprint) || prior && (prior.fingerprint !== fingerprint || prior.retryOf === job.id)) continue;
    const found = receipts.findIndex(row => row.fingerprint === fingerprint);
    // A human may have reserved another attempt with the same settings. An old
    // list response must never replace that attempt, including an uncertain POST.
    if (found >= 0 && receipts[found].retryOf && receipts[found].idempotencyKey !== job.idempotencyKey) continue;
    matched.add(fingerprint);
    const receipt: HQOperation = { fingerprint, idempotencyKey: job.idempotencyKey, jobId: job.id, retryOf: prior?.retryOf, delivery: "submitted" };
    if (found < 0) receipts.push(receipt); else receipts[found] = receipt;
  }
  // Persist only receipts qualified for this execution basis before enabling creation.
  localStorage.setItem(operationsKey, JSON.stringify(receipts));
  return receipts;
}
export function reserveHQOperation(body: Omit<HQCreateRequest, "idempotencyKey">, jobs: HQJob[]) {
  const receipts = reconcileHQOperations(jobs), fingerprint = hqFingerprint(body), previous = receipts.find(r => r.fingerprint === fingerprint);
  if (!previous && jobs.some(job => currentExecution(job) && hqActive(job) && !hqJobFingerprint(job) && !receipts.some(row => row.idempotencyKey === job.idempotencyKey))) {
    throw new Error("已有下载中任务尚未返回完整三图编号，请先刷新核对，暂不创建新请求");
  }
  const operation: HQOperation = previous || { fingerprint, idempotencyKey: `hq-local-${hqExecutionBasis}-${crypto.randomUUID()}`, delivery: "prepared" };
  // If browser storage fails, fail before POST, so an uncertain request remains recoverable.
  saveHQOperation(operation);
  return operation;
}
export function retryableHQJob(operation: HQOperation | undefined, jobs: HQJob[]): HQJob | undefined {
  if (!operation?.jobId || operation.delivery !== "submitted") return;
  const job = jobs.find(item => item.id === operation.jobId);
  if (!job || !["failed", "cancelled"].includes(job.state) || job.idempotencyKey !== operation.idempotencyKey || !hasCurrentBasis(job)) return;
  const fingerprint = jobSettingsFingerprint(job);
  // An owned preparation failure can precede creation of the identity child.
  if (fingerprint && fingerprint !== operation.fingerprint) return;
  if (jobs.some(item => {
    if (!hqActive(item) || !hasCurrentBasis(item)) return false;
    const other = jobSettingsFingerprint(item);
    return !other || other === operation.fingerprint;
  })) return;
  return job;
}
// Only the explicit terminal-retry UI calls this. Ordinary create/refresh always
// reserves the current attempt through reserveHQOperation instead.
export async function reserveHQRetry(body: Omit<HQCreateRequest, "idempotencyKey">, jobs: HQJob[], expectedKey: string): Promise<HQOperation> {
  const previous = reconcileHQOperations(jobs).find(row => row.fingerprint === hqFingerprint(body));
  if (!previous || previous.idempotencyKey !== expectedKey) throw new Error("请求回执已更新，请先刷新核对当前尝试");
  const terminal = retryableHQJob(previous, jobs);
  if (!terminal) throw new Error("仅服务确认失败或已取消且没有同组运行任务时，可按相同设置新建重试");
  // One successor per terminal attempt, even if two tabs confirm concurrently.
  // A later failed successor has a different job ID and gets its own fresh key.
  const successor = await sha256Hex(new TextEncoder().encode(JSON.stringify([hqExecutionBasis, terminal.id, expectedKey])));
  const next: HQOperation = { fingerprint: previous.fingerprint, idempotencyKey: `hq-local-${hqExecutionBasis}-retry-${successor}`, retryOf: terminal.id, delivery: "prepared" };
  persistHQOperation(next, previous.idempotencyKey);
  return next;
}
export function writeHQDraft(draft: HQDraft) {
  const selection: HQDraft["selection"] = {};
  for (const role of ["person", "garment", "pose"] as const) {
    const item = draft.selection[role];
    if (item && validId(item.id)) selection[role] = { id: item.id, label: item.label || item.name || item.id };
  }
  try { sessionStorage.setItem(draftKey, JSON.stringify({ selection, parameters: cleanParameters(draft.parameters), ...cleanIdentity(draft), activeJobId: validId(draft.activeJobId) ? draft.activeJobId : undefined })); } catch { /* Receipt storage is checked separately before creating a job. */ }
}
export function readHQDraft(): HQDraft | null {
  try {
    const data = JSON.parse(sessionStorage.getItem(draftKey) || "null");
    if (!data?.selection || !validHQParameters(data.parameters)) return null;
    const selection: HQDraft["selection"] = {};
    for (const role of ["person", "garment", "pose"] as const) if (validId(data.selection[role]?.id)) selection[role] = { id: data.selection[role].id, label: String(data.selection[role].label || data.selection[role].id) };
    return { selection, parameters: cleanParameters(data.parameters), ...cleanIdentity(data), activeJobId: validId(data.activeJobId) ? data.activeJobId : undefined };
  } catch { return null; }
}
