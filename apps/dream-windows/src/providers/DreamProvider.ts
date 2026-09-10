import type { HardwareSnapshot } from "../domain/hardware";
import type { ModelRecord } from "../domain/models";
import type { Experiment, ExperimentRequest } from "../domain/experiment";
import type { GenerationJob, GenerationRequest, JobHandle } from "../domain/generation";
import type { HistoryItem, HistoryPage, HistoryQuery } from "../domain/history";
import type { ResearchStatus, RuntimeAttentionIndex, RuntimeAttentionMap, RuntimeCapabilities, RuntimeTraceResponse, RuntimeTraceSummary } from "../domain/trace";
import type { DreamSettings, WorkspaceEntry, WorkspaceOpenResult } from "../domain/settings";

export type { ExperimentRequest } from "../domain/experiment";

export interface DreamProvider {
  readonly mode: "mock" | "backend";
  getHardware(): Promise<HardwareSnapshot>;
  getCapabilities(): Promise<RuntimeCapabilities>;
  listModels(): Promise<ModelRecord[]>;
  getModel(id: string): Promise<ModelRecord>;
  verifyModel(id: string): Promise<ModelRecord>;
  reindexModels(): Promise<ModelRecord[]>;
  generate(req: GenerationRequest): Promise<JobHandle>;
  getJob(id: string): Promise<GenerationJob>;
  cancelJob(id: string): Promise<GenerationJob>;
  listHistory(query: HistoryQuery): Promise<HistoryPage>;
  getHistoryItem(id: string): Promise<HistoryItem>;
  deleteHistory(id: string): Promise<void>;
  favoriteHistory(id: string, value: boolean): Promise<void>;
  runExperiment(req: ExperimentRequest): Promise<Experiment>;
  getExperiment(id: string): Promise<Experiment>;
  listRuntimeTraces(): Promise<RuntimeTraceSummary[]>;
  getRuntimeTrace(runId: string): Promise<RuntimeTraceResponse>;
  getAttentionIndex(runId: string): Promise<RuntimeAttentionIndex>;
  getAttentionMap(runId: string, mapId: string): Promise<RuntimeAttentionMap>;
  getResearchStatus(): Promise<ResearchStatus>;
  getSettings(): Promise<DreamSettings>;
  updateSettings(updates: Partial<DreamSettings>): Promise<DreamSettings>;
  openWorkspace(entry: WorkspaceEntry): Promise<WorkspaceOpenResult>;
}
