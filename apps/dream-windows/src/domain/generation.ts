import type { TruthLevel } from "./hardware";

export type GenerationRequest = {
  prompt: string;
  negativePrompt: string;
  modelId: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  samplingMethod?: "dpm++2m" | "dpm++2m_sde" | "lcm" | "euler" | "euler_a";
  scheduler?: "karras" | "discrete" | "exponential" | "lcm";
  seed: number | "random";
  fusionMode: string;
  traceLevel: "off" | "basic" | "h6" | "h7";
};

export type GenerationState = "idle" | "queued" | "preparing" | "sampling" | "decoding" | "saving" | "complete" | "failed" | "cancelled";

export type GenerationResult = {
  id: string;
  imageUrl: string;
  truth: TruthLevel;
  metadata: Record<string, unknown>;
};

export type GenerationJob = {
  id: string;
  request: GenerationRequest;
  state: GenerationState;
  progress: number;
  message: string;
  result?: GenerationResult;
  error?: string;
};

export type JobHandle = { id: string };

export type GenerationPreset = {
  id: string;
  name: string;
  request: GenerationRequest;
};

export type GenerationBatchItem = {
  id: string;
  request: GenerationRequest;
  state: GenerationState;
  progress: number;
  message: string;
  result?: GenerationResult;
  error?: string;
};

export type GenerationBatch = GenerationBatchItem[];
