import hardwareFixture from "../fixtures/hardware.json";
import modelFixtures from "../fixtures/models.json";
import historyFixtures from "../fixtures/history.json";
import { mockImages } from "../fixtures/mockImages";
import type { Experiment, ExperimentVariant } from "../domain/experiment";
import type { HardwareSnapshot } from "../domain/hardware";
import type { ModelRecord } from "../domain/models";
import type { GenerationJob, GenerationRequest, JobHandle } from "../domain/generation";
import type { HistoryItem, HistoryPage, HistoryQuery } from "../domain/history";
import type { ResearchStatus, RuntimeAttentionIndex, RuntimeAttentionMap, RuntimeCapabilities, RuntimeTrace, RuntimeTraceSummary } from "../domain/trace";
import type { DreamSettings, WorkspaceEntry, WorkspaceOpenResult } from "../domain/settings";
import type { DreamProvider, ExperimentRequest } from "./DreamProvider";
import type { RuntimeInfluence, RuntimeSelfAttentionIndex, RuntimeSelfAttentionMapResponse } from "../domain/trace";

type FixtureModel = Omit<ModelRecord, "imageUrl"> & { imageKey: keyof typeof mockImages };
type FixtureHistory = Omit<HistoryItem, "imageUrl"> & { imageKey: keyof typeof mockImages };

const imageFor = (key: keyof typeof mockImages) => mockImages[key];

export class MockDreamProvider implements DreamProvider {
  readonly mode = "mock" as const;
  private readonly jobs = new Map<string, { request: GenerationRequest; startedAt: number; cancelled?: boolean }>();
  private readonly experiments = new Map<string, Experiment>();
  private readonly history = (historyFixtures as FixtureHistory[]).map((item) => ({ ...item, imageUrl: imageFor(item.imageKey) }));
  private jobCounter = 0;
  private experimentCounter = 0;

  async getHardware(): Promise<HardwareSnapshot> {
    return { ...(hardwareFixture as HardwareSnapshot) };
  }

  async getCapabilities(): Promise<RuntimeCapabilities> {
    return {
      nativeGeneration: { available: true, truth: "observed" },
      processTrace: { available: true, truth: "derived" },
      latentTrace: { available: true, truth: "observed" },
      semanticExperiments: { available: true, truth: "demo", message: "测试提供方使用固定样例" },
      attention: { available: false, truth: "unavailable", message: "研究引擎未连接" },
    };
  }

  async listModels(): Promise<ModelRecord[]> {
    return (modelFixtures as FixtureModel[]).map(({ imageKey, ...model }) => ({ ...model, imageUrl: imageFor(imageKey) }));
  }

  async getModel(id: string): Promise<ModelRecord> {
    const model = (await this.listModels()).find((item) => item.id === id);
    if (!model) throw new Error(`Model not found: ${id}`);
    return model;
  }

  async verifyModel(id: string): Promise<ModelRecord> {
    return this.getModel(id);
  }

  async reindexModels(): Promise<ModelRecord[]> {
    return this.listModels();
  }

  async generate(request: GenerationRequest): Promise<JobHandle> {
    const id = `mock-job-${++this.jobCounter}`;
    this.jobs.set(id, { request, startedAt: Date.now() });
    return { id };
  }

  async getJob(id: string): Promise<GenerationJob> {
    const job = this.jobs.get(id);
    if (!job) throw new Error(`Generation job not found: ${id}`);
    if (job.cancelled) return { id, request: job.request, state: "cancelled", progress: 0, message: "已取消生成" };
    const elapsed = Date.now() - job.startedAt;
    const state = elapsed < 120 ? "queued" : elapsed < 240 ? "preparing" : elapsed < 420 ? "sampling" : elapsed < 520 ? "decoding" : "complete";
    const progress = state === "queued" ? 4 : state === "preparing" ? 18 : state === "sampling" ? Math.min(86, 22 + Math.floor((elapsed - 240) / 8)) : state === "decoding" ? 94 : 100;
    return {
      id,
      request: job.request,
      state,
      progress,
      message: state === "queued" ? "等待本地队列" : state === "preparing" ? "正在加载模型并准备 CUDA" : state === "sampling" ? `采样步骤 ${Math.min(job.request.steps, Math.max(1, Math.floor((elapsed - 240) / 30)))} / ${job.request.steps}` : state === "decoding" ? "正在解码 VAE 输出" : "模拟生成完成",
      result: state === "complete" ? {
        id: `mock-result-${id}`,
        imageUrl: mockImages.lake,
        truth: "demo",
        metadata: { backend: "mock", modelId: job.request.modelId, width: job.request.width, height: job.request.height },
      } : undefined,
    };
  }

  async cancelJob(id: string): Promise<GenerationJob> {
    const job = this.jobs.get(id);
    if (!job) throw new Error(`Generation job not found: ${id}`);
    job.cancelled = true;
    return { id, request: job.request, state: "cancelled", progress: 0, message: "已取消生成" };
  }

  async listHistory(query: HistoryQuery): Promise<HistoryPage> {
    const needle = query.search?.trim().toLowerCase();
    const filtered = this.history.filter((item) => {
      const matchesSearch = !needle || [item.title, item.prompt, item.modelName, ...item.tags].join(" ").toLowerCase().includes(needle);
      const matchesFilter = !query.filter || query.filter === "all" || (query.filter === "favorites" && item.favorite) || (query.filter === "failed" && item.status === "failed") || (query.filter === "tagged" && item.tags.length > 0) || (query.filter === "today" && item.createdAt.startsWith("2026-09-06"));
      return matchesSearch && matchesFilter;
    });
    const start = (query.page - 1) * query.pageSize;
    return { items: filtered.slice(start, start + query.pageSize), total: filtered.length, page: query.page, pageSize: query.pageSize };
  }

  async getHistoryItem(id: string): Promise<HistoryItem> {
    const item = this.history.find((entry) => entry.id === id);
    if (!item) throw new Error(`History item not found: ${id}`);
    return { ...item };
  }

  async deleteHistory(id: string): Promise<void> {
    const index = this.history.findIndex((item) => item.id === id);
    if (index < 0) throw new Error(`History item not found: ${id}`);
    this.history.splice(index, 1);
  }

  async favoriteHistory(id: string, value: boolean): Promise<void> {
    const item = this.history.find((entry) => entry.id === id);
    if (!item) throw new Error(`History item not found: ${id}`);
    item.favorite = value;
  }

  async runExperiment(request: ExperimentRequest): Promise<Experiment> {
    const imageKeys: Array<keyof typeof mockImages> = ["lake", "forest", "castle", "portrait"];
    let specs: Array<{ label: string; modelId: string }>;
    if (request.kind === "model") {
      const readyModels = (await this.listModels()).filter((model) => model.status === "ready");
      const requestedModel = readyModels.find((model) => model.id === request.modelId);
      if (!requestedModel) throw new Error(`Model is unavailable for comparison: ${request.modelId}`);
      specs = [requestedModel, ...readyModels.filter((model) => model.id !== request.modelId)]
        .slice(0, 4)
        .map((model) => ({ label: model.displayName, modelId: model.id }));
    } else if (request.kind === "steps") {
      specs = [8, 16, 24, request.steps ?? 20].map((steps) => ({ label: `${steps} 步`, modelId: request.modelId }));
    } else {
      specs = ["完整提示词（控制组）", "平衡描述改写", "仅首段提示词", "重点描述改写"]
        .map((label) => ({ label, modelId: request.modelId }));
    }
    const variants: ExperimentVariant[] = specs.map((spec, index) => ({
      id: `variant-${index}`,
      label: spec.label,
      modelId: spec.modelId,
      imageUrl: imageFor(imageKeys[index]),
      state: "complete",
    }));
    const experiment: Experiment = { id: `mock-experiment-${++this.experimentCounter}`, kind: request.kind, seed: request.seed, lockedFields: request.kind === "model" ? ["seed"] : ["seed", "modelId"], variants, status: "complete", message: "测试提供方实验已完成" };
    this.experiments.set(experiment.id, experiment);
    return experiment;
  }

  async getExperiment(id: string): Promise<Experiment> {
    const experiment = this.experiments.get(id);
    if (!experiment) throw new Error(`Experiment not found: ${id}`);
    return experiment;
  }

  async listRuntimeTraces(): Promise<RuntimeTraceSummary[]> {
    return [{
      runId: "mock-trace",
      totalTimeMs: 36151,
      modelId: "mock-model",
      steps: 28,
      backend: "测试提供方",
      hasAttention: false,
      hasLatent: false,
      modifiedAt: "2026-09-09T00:00:00+00:00",
      truth: "observed",
    }];
  }

  async getRuntimeTrace(runId: string): Promise<RuntimeTrace> {
    return {
      available: true,
      truth: "demo",
      runId,
      totalTimeMs: 36151,
      nodes: [
        { id: "prompt", name: "Prompt", backend: "CPU", expectedCalls: 1, expectedCallsTruth: "derived", durationMs: 12, status: "executed", truth: "demo" },
        { id: "unet", name: "UNet chunks", backend: "CUDA FP16", expectedCalls: 8, expectedCallsTruth: "derived", durationMs: 27800, status: "executed", truth: "demo" },
        { id: "attention", name: "H7 Attention", backend: "Research", status: "skipped", truth: "unavailable" },
      ],
    };
  }

  async getAttentionIndex(runId: string): Promise<RuntimeAttentionIndex> {
    return { available: false, runId, message: "测试提供方没有原生 H7 注意力张量", truth: "unavailable" };
  }

  async getAttentionMap(_runId: string, _mapId: string): Promise<RuntimeAttentionMap> {
    throw new Error("ATTENTION_MAP_NOT_FOUND: 测试提供方没有原生 H7 注意力张量");
  }

  async getInfluence(runId: string): Promise<RuntimeInfluence> {
    return { available: false, runId, truth: "unavailable", message: "当前 native 记录没有导出条件影响张量；测试提供方不提供实测研究数据。" };
  }

  async getSelfAttentionIndex(runId: string): Promise<RuntimeSelfAttentionIndex> {
    return { available: false, runId, truth: "unavailable", message: "测试提供方没有原生 H7 自注意力张量" };
  }

  async getSelfAttentionMap(runId: string, _mapId: string): Promise<RuntimeSelfAttentionMapResponse> {
    return { available: false, runId, truth: "unavailable", message: "测试提供方没有原生 H7 自注意力空间图" };
  }

  async getResearchStatus(): Promise<ResearchStatus> {
    return { available: false, message: "Research Engine unavailable in this GUI Alpha", truth: "unavailable" };
  }

  async getSettings(): Promise<DreamSettings> {
    return {
      dreamRoot: "E:\\Dream",
      modelsPath: "E:\\Dream\\models",
      outputsPath: "E:\\Dream\\outputs",
      historyPath: "E:\\Dream\\history",
      cachePath: "E:\\Dream\\cache",
      logsPath: "E:\\Dream\\logs",
      autopilotEnabled: true,
      precisionMode: "fp16",
      fallbackToCpu: true,
      tileMode: "automatic",
      vaeMemoryMode: "sliced",
      attentionSlicing: true,
      vramThresholdGb: 4,
      optimizationLevel: "balanced",
    };
  }

  async updateSettings(updates: Partial<DreamSettings>): Promise<DreamSettings> {
    return { ...(await this.getSettings()), ...updates } as DreamSettings;
  }

  async openWorkspace(entry: WorkspaceEntry): Promise<WorkspaceOpenResult> {
    const suffix = entry === "base" ? "" : `\\${entry}`;
    return { opened: true, entry, path: `E:\\Dream${suffix}` };
  }
}
