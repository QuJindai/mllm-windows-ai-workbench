import type { HardwareSnapshot } from "../domain/hardware";
import type { Experiment } from "../domain/experiment";
import type { GenerationJob, GenerationRequest, JobHandle } from "../domain/generation";
import type { HistoryItem, HistoryPage, HistoryQuery } from "../domain/history";
import type { ModelRecord } from "../domain/models";
import type { ResearchStatus, RuntimeAttentionIndex, RuntimeAttentionMap, RuntimeCapabilities, RuntimeCapability, RuntimeTraceResponse, RuntimeTraceSummary } from "../domain/trace";
import type { DreamSettings, WorkspaceEntry, WorkspaceOpenResult } from "../domain/settings";
import type { DreamProvider, ExperimentRequest } from "./DreamProvider";

type ApiError = { code?: string; message?: string };

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { method: init.method ?? "GET", ...init, headers: { "Content-Type": "application/json", ...(init.headers ?? {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = body as ApiError;
    throw new Error(`${error.code ?? `HTTP_${response.status}`}: ${error.message ?? "Request failed"}`);
  }
  return body as T;
}

export class DreamHttpProvider implements DreamProvider {
  readonly mode = "backend" as const;

  getHardware(): Promise<HardwareSnapshot> {
    return requestJson<HardwareSnapshot>("/api/hardware");
  }

  async getCapabilities(): Promise<RuntimeCapabilities> {
    const raw = await requestJson<Record<string, RuntimeCapability | undefined>>("/api/capabilities");
    const capability = (camel: string, snake: string): RuntimeCapability => {
      const value = raw[camel] ?? raw[snake];
      if (!value) return { available: false, truth: "unavailable", message: "能力状态未返回" };
      if (value.truth !== "observed" && value.truth !== "derived" && value.truth !== "unavailable") {
        return { available: false, truth: "unavailable", message: value.message ?? "能力只返回了非生产数据" };
      }
      return value;
    };
    return {
      nativeGeneration: capability("nativeGeneration", "native_generation"),
      processTrace: capability("processTrace", "process_trace"),
      latentTrace: capability("latentTrace", "latent_trace"),
      semanticExperiments: capability("semanticExperiments", "semantic_experiments"),
      attention: capability("attention", "attention"),
    };
  }

  listModels(): Promise<ModelRecord[]> {
    return requestJson<ModelRecord[]>("/api/models");
  }

  getModel(id: string): Promise<ModelRecord> {
    return requestJson<ModelRecord>(`/api/models/${encodeURIComponent(id)}`);
  }

  verifyModel(id: string): Promise<ModelRecord> {
    return requestJson<ModelRecord>(`/api/models/${encodeURIComponent(id)}/verify`, { method: "POST" });
  }

  reindexModels(): Promise<ModelRecord[]> {
    return requestJson<ModelRecord[]>("/api/models/reindex", { method: "POST" });
  }

  async generate(request: GenerationRequest): Promise<JobHandle> {
    const job = await requestJson<{ id: string }>("/api/generate", { method: "POST", body: JSON.stringify(request) });
    return { id: job.id };
  }

  getJob(id: string): Promise<GenerationJob> {
    return requestJson<GenerationJob>(`/api/jobs/${encodeURIComponent(id)}`);
  }

  cancelJob(id: string): Promise<GenerationJob> {
    return requestJson<GenerationJob>(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
  }

  listHistory(query: HistoryQuery): Promise<HistoryPage> {
    const params = new URLSearchParams({ page: String(query.page), page_size: String(query.pageSize), filter: query.filter ?? "all", search: query.search ?? "" });
    return requestJson<HistoryPage>(`/api/history?${params.toString()}`);
  }

  getHistoryItem(id: string): Promise<HistoryItem> {
    return requestJson<HistoryItem>(`/api/history/${encodeURIComponent(id)}`);
  }

  async deleteHistory(id: string): Promise<void> {
    await requestJson(`/api/history/${encodeURIComponent(id)}`, { method: "DELETE" });
  }

  async favoriteHistory(id: string, value: boolean): Promise<void> {
    await requestJson(`/api/history/${encodeURIComponent(id)}/favorite`, { method: "POST", body: JSON.stringify({ value }) });
  }

  runExperiment(request: ExperimentRequest): Promise<Experiment> {
    return requestJson<Experiment>("/api/experiments", { method: "POST", body: JSON.stringify(request) });
  }

  getExperiment(id: string): Promise<Experiment> {
    return requestJson<Experiment>(`/api/experiments/${encodeURIComponent(id)}`);
  }

  listRuntimeTraces(): Promise<RuntimeTraceSummary[]> {
    return requestJson<RuntimeTraceSummary[]>("/api/traces");
  }

  getRuntimeTrace(runId: string): Promise<RuntimeTraceResponse> {
    return requestJson<RuntimeTraceResponse>(`/api/traces/${encodeURIComponent(runId)}`);
  }

  getAttentionIndex(runId: string): Promise<RuntimeAttentionIndex> {
    return requestJson<RuntimeAttentionIndex>(`/api/traces/${encodeURIComponent(runId)}/attention`);
  }

  getAttentionMap(runId: string, mapId: string): Promise<RuntimeAttentionMap> {
    return requestJson<RuntimeAttentionMap>(`/api/traces/${encodeURIComponent(runId)}/attention/maps/${encodeURIComponent(mapId)}`);
  }

  getResearchStatus(): Promise<ResearchStatus> {
    return requestJson<ResearchStatus>("/api/research/status");
  }

  getSettings(): Promise<DreamSettings> {
    return requestJson<DreamSettings>("/api/settings");
  }

  updateSettings(updates: Partial<DreamSettings>): Promise<DreamSettings> {
    return requestJson<DreamSettings>("/api/settings", { method: "PUT", body: JSON.stringify(updates) });
  }

  openWorkspace(entry: WorkspaceEntry): Promise<WorkspaceOpenResult> {
    return requestJson<WorkspaceOpenResult>("/api/workspace/open", { method: "POST", body: JSON.stringify({ entry }) });
  }
}

export function createDreamProvider(): DreamProvider {
  return new DreamHttpProvider();
}
