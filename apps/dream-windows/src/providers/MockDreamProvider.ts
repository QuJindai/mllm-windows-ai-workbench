import hardwareFixture from "../fixtures/hardware.json";
import modelFixtures from "../fixtures/models.json";
import historyFixtures from "../fixtures/history.json";
import { mockImages } from "../fixtures/mockImages";
import type { Experiment, ExperimentVariant } from "../domain/experiment";
import type { HardwareSnapshot } from "../domain/hardware";
import type { ModelRecord } from "../domain/models";
import type { GenerationJob, GenerationRequest, JobHandle } from "../domain/generation";
import type { HistoryItem, HistoryPage, HistoryQuery } from "../domain/history";
import type { ResearchStatus, RuntimeTrace } from "../domain/trace";
import type { DreamProvider, ExperimentRequest } from "./DreamProvider";

type FixtureModel = Omit<ModelRecord, "imageUrl"> & { imageKey: keyof typeof mockImages };
type FixtureHistory = Omit<HistoryItem, "imageUrl"> & { imageKey: keyof typeof mockImages };

const imageFor = (key: keyof typeof mockImages) => mockImages[key];

export class MockDreamProvider implements DreamProvider {
  readonly mode = "mock" as const;
  private readonly jobs = new Map<string, { request: GenerationRequest; startedAt: number }>();
  private readonly history = (historyFixtures as FixtureHistory[]).map((item) => ({ ...item, imageUrl: imageFor(item.imageKey) }));
  private jobCounter = 0;

  async getHardware(): Promise<HardwareSnapshot> {
    return { ...(hardwareFixture as HardwareSnapshot) };
  }

  async listModels(): Promise<ModelRecord[]> {
    return (modelFixtures as FixtureModel[]).map(({ imageKey, ...model }) => ({ ...model, imageUrl: imageFor(imageKey) }));
  }

  async getModel(id: string): Promise<ModelRecord> {
    const model = (await this.listModels()).find((item) => item.id === id);
    if (!model) throw new Error(`Model not found: ${id}`);
    return model;
  }

  async generate(request: GenerationRequest): Promise<JobHandle> {
    const id = `mock-job-${++this.jobCounter}`;
    this.jobs.set(id, { request, startedAt: Date.now() });
    return { id };
  }

  async getJob(id: string): Promise<GenerationJob> {
    const job = this.jobs.get(id);
    if (!job) throw new Error(`Generation job not found: ${id}`);
    const elapsed = Date.now() - job.startedAt;
    const state = elapsed < 120 ? "queued" : elapsed < 240 ? "preparing" : elapsed < 420 ? "sampling" : elapsed < 520 ? "decoding" : "complete";
    const progress = state === "queued" ? 4 : state === "preparing" ? 18 : state === "sampling" ? Math.min(86, 22 + Math.floor((elapsed - 240) / 8)) : state === "decoding" ? 94 : 100;
    return {
      id,
      request: job.request,
      state,
      progress,
      message: state === "queued" ? "Waiting for the local queue" : state === "preparing" ? "Loading model and preparing CUDA" : state === "sampling" ? `Sampling step ${Math.min(job.request.steps, Math.max(1, Math.floor((elapsed - 240) / 30)))} / ${job.request.steps}` : state === "decoding" ? "Decoding VAE output" : "Mock generation complete",
      result: state === "complete" ? {
        id: `mock-result-${id}`,
        imageUrl: mockImages.lake,
        truth: "demo",
        metadata: { backend: "mock", modelId: job.request.modelId, width: job.request.width, height: job.request.height },
      } : undefined,
    };
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
    const labels = ["Baseline", "Equal Mean", "First Only", "Token Weighted"];
    const variants: ExperimentVariant[] = labels.map((label, index) => ({ id: `variant-${index}`, label, imageUrl: imageFor(index === 0 ? "lake" : index === 1 ? "forest" : index === 2 ? "castle" : "portrait"), metric: Number((8.19 + index * 0.09).toFixed(2)) }));
    return { id: `experiment-${Date.now()}`, kind: request.kind, seed: request.seed, lockedFields: ["seed", "modelId"], variants };
  }

  async getRuntimeTrace(runId: string): Promise<RuntimeTrace> {
    return { runId, totalTimeMs: 36151, nodes: [{ id: "prompt", name: "Prompt", backend: "CPU", expectedCalls: 1, observedCalls: 1, durationMs: 12, status: "executed", truth: "observed" }, { id: "unet", name: "UNet chunks", backend: "CUDA FP16", expectedCalls: 8, observedCalls: 8, durationMs: 27800, status: "executed", truth: "observed" }, { id: "attention", name: "H7 Attention", backend: "Research", expectedCalls: 0, observedCalls: 0, durationMs: 0, status: "skipped", truth: "unavailable" }] };
  }

  async getResearchStatus(): Promise<ResearchStatus> {
    return { available: false, message: "Research Engine unavailable in this GUI Alpha", truth: "unavailable" };
  }
}
