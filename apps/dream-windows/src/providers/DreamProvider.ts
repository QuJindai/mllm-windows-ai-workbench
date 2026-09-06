import type { HardwareSnapshot } from "../domain/hardware";
import type { ModelRecord } from "../domain/models";
import type { Experiment } from "../domain/experiment";
import type { GenerationJob, GenerationRequest, JobHandle } from "../domain/generation";
import type { HistoryItem, HistoryPage, HistoryQuery } from "../domain/history";
import type { ResearchStatus, RuntimeTrace } from "../domain/trace";

export type ExperimentRequest = {
  kind: "fusion" | "steps" | "model";
  seed: number;
  modelId: string;
};

export interface DreamProvider {
  readonly mode: "mock" | "backend";
  getHardware(): Promise<HardwareSnapshot>;
  listModels(): Promise<ModelRecord[]>;
  getModel(id: string): Promise<ModelRecord>;
  generate(req: GenerationRequest): Promise<JobHandle>;
  getJob(id: string): Promise<GenerationJob>;
  listHistory(query: HistoryQuery): Promise<HistoryPage>;
  getHistoryItem(id: string): Promise<HistoryItem>;
  deleteHistory(id: string): Promise<void>;
  favoriteHistory(id: string, value: boolean): Promise<void>;
  runExperiment(req: ExperimentRequest): Promise<Experiment>;
  getRuntimeTrace(runId: string): Promise<RuntimeTrace>;
  getResearchStatus(): Promise<ResearchStatus>;
}
