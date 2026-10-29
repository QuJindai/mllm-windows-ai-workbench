export type RefinementMode = "restore" | "redraw" | "reference-anchor" | "edge-lighting";
export type RefinementVersion = {
  id: string;
  state: "queued" | "running" | "complete" | "failed" | "cancelled";
  message: string;
  error?: string | null;
  imageUrl?: string | null;
  createdAt: string;
  parentVersionId: string | null;
  settings: Record<string, unknown>;
  metrics?: Record<string, unknown>;
};
export type RefinementSnapshot = {
  sourceJobId: string;
  selectedVersionId: string;
  versions: RefinementVersion[];
  modes?: string[];
  defaultMode?: string;
  usesDiffusion?: boolean;
};
export type RefinementRequest = {
  sourceJobId: string;
  parentVersionId: string;
  mode: RefinementMode;
  strength: number;
  prompt: string;
  negativePrompt: string;
  seed: number;
  requestId?: string;
};

export class RefinementHttpError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

function errorMessage(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(errorMessage).filter(Boolean).join("；");
  if (value && typeof value === "object") {
    const body = value as Record<string, unknown>;
    return errorMessage(body.detail ?? body.message ?? body.msg ?? body.error);
  }
}

async function request(path: string, init: RequestInit = {}): Promise<unknown> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  init.signal?.addEventListener("abort", abort, { once: true });
  if (init.signal?.aborted) controller.abort();
  let timedOut = false;
  const timeout = window.setTimeout(() => { timedOut = true; controller.abort(); }, 15000);
  try {
    const response = await fetch(`/api/identity${path}`, {
      ...init, signal: controller.signal, credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...init.headers },
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) throw new RefinementHttpError(errorMessage(body) || `精修请求失败（HTTP ${response.status}）`, response.status);
    if (!body) throw new Error("精修服务未返回有效数据");
    return body;
  } catch (error) {
    if (timedOut) throw new Error("精修请求超时，请先读取版本确认状态");
    throw error;
  } finally {
    window.clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

function version(value: unknown): RefinementVersion {
  const item = value as Partial<RefinementVersion> | null;
  if (!item || typeof item.id !== "string" || !item.id || !["queued", "running", "complete", "failed", "cancelled"].includes(item.state ?? "")
    || typeof item.message !== "string" || typeof item.createdAt !== "string"
    || !(item.parentVersionId === null || typeof item.parentVersionId === "string")
    || !item.settings || typeof item.settings !== "object" || Array.isArray(item.settings)
    || !(item.imageUrl == null || typeof item.imageUrl === "string")) throw new Error("精修服务返回的版本记录无效");
  return item as RefinementVersion;
}

function snapshot(value: unknown, sourceJobId: string): RefinementSnapshot {
  const data = value as Partial<RefinementSnapshot> | null;
  if (!data || data.sourceJobId !== sourceJobId || typeof data.selectedVersionId !== "string" || !Array.isArray(data.versions)
    || data.modes !== undefined && (!Array.isArray(data.modes) || data.modes.some(mode => typeof mode !== "string"))
    || data.defaultMode !== undefined && typeof data.defaultMode !== "string"
    || data.usesDiffusion !== undefined && typeof data.usesDiffusion !== "boolean") throw new Error("精修服务返回的版本列表无效");
  const versions = data.versions.map(version);
  if (new Set(versions.map(item => item.id)).size !== versions.length || !versions.some(item => item.id === data.selectedVersionId)) {
    throw new Error("精修服务返回的版本选择无效");
  }
  return { ...data, versions } as RefinementSnapshot;
}

export const refinementApi = {
  list: async (sourceJobId: string, signal?: AbortSignal) => snapshot(await request(`/jobs/${encodeURIComponent(sourceJobId)}/refinements`, { signal }), sourceJobId),
  create: async (body: RefinementRequest, signal?: AbortSignal) => version(await request("/refinements", { method: "POST", body: JSON.stringify(body), signal })),
  cancel: async (id: string, signal?: AbortSignal) => {
    const result = version(await request(`/refinements/${encodeURIComponent(id)}/cancel`, { method: "POST", signal }));
    if (result.id !== id) throw new Error("取消精修未得到对应版本的确认");
    return result;
  },
  select: async (sourceJobId: string, versionId: string, signal?: AbortSignal) => snapshot(await request(`/jobs/${encodeURIComponent(sourceJobId)}/refinements/select`, {
    method: "POST", body: JSON.stringify({ versionId }), signal,
  }), sourceJobId),
};
