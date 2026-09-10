export type ExperimentRequest = {
  kind: "fusion" | "steps" | "model";
  seed: number;
  modelId: string;
  prompt: string;
  negativePrompt?: string;
  steps?: number;
  cfg?: number;
};

export type ExperimentVariant = {
  id: string;
  label: string;
  modelId: string;
  imageUrl?: string;
  metric?: number;
  jobId?: string;
  state?: "queued" | "preparing" | "sampling" | "decoding" | "complete" | "failed" | "cancelled";
  error?: string;
};

export type Experiment = {
  id: string;
  kind: "fusion" | "steps" | "model";
  seed: number;
  lockedFields: string[];
  variants: ExperimentVariant[];
  status?: "queued" | "running" | "complete" | "failed";
  message?: string;
};
