import type { HardwareSnapshot, TruthLevel } from "./hardware";

export type RuntimeNode = {
  id: string;
  name: string;
  backend: string;
  shape?: string;
  expectedCalls?: number;
  expectedCallsTruth?: "derived";
  observedCalls?: number;
  observedCallsTruth?: "observed";
  durationMs?: number;
  status: "executed" | "running" | "skipped" | "error";
  truth: TruthLevel;
};

export type RuntimeTraceEvent = {
  phase: string;
  label: string;
  durationMs: number;
  truth: TruthLevel;
};

export type RuntimeTracePreviewFrame = {
  step: number;
  fileName: string;
  imageUrl?: string;
  truth: "observed";
  kind: "latent-projection";
};

export type RuntimeLatentChannel = {
  channel: number;
  fileName: string;
  imageUrl?: string;
  min: number;
  max: number;
  mean: number;
  std: number;
  l2: number;
  histogram: number[];
  truth: "observed";
  kind: "latent-channel";
};

export type RuntimeLatentTelemetry = {
  step: number;
  shape: number[];
  mean: number;
  std: number;
  l2: number;
  deltaL2?: number | null;
  deltaMeanAbs?: number | null;
  deltaFileName?: string;
  deltaImageUrl?: string;
  cosine?: number | null;
  channels: RuntimeLatentChannel[];
  channelCorrelation?: (number | null)[][];
  correlationMethod?: "pearson";
  truth: "observed";
  kind: "latent-state";
};

export type RuntimeAttentionToken = {
  slot: number;
  tokenId: number;
  text: string;
  chunk: number;
  weight: number;
};

export type RuntimeAttentionLayer = {
  id: string;
  stage: "down" | "mid" | "up";
  label: string;
};

export type RuntimeAttentionMapDescriptor = {
  id: string;
  step: number;
  layerId: string;
  tokenSlot: number;
  width: number;
  height: number;
  entropy: number;
  peak: number;
  coverage: number;
  mapUrl: string;
};

export type RuntimeAttentionIndexAvailable = {
  available: true;
  runId: string;
  contractVersion: "h7-attention-v1";
  kind: "cross-attention";
  truth: "observed";
  source: "debug-unet" | "diffusers-unet";
  tokens: RuntimeAttentionToken[];
  layers: RuntimeAttentionLayer[];
  maps: RuntimeAttentionMapDescriptor[];
};

export type RuntimeAttentionUnavailable = {
  available: false;
  runId: string;
  message: string;
  truth: "unavailable";
};

export type RuntimeAttentionIndex = RuntimeAttentionIndexAvailable | RuntimeAttentionUnavailable;

export type RuntimeAttentionMap = Omit<RuntimeAttentionIndexAvailable, "tokens" | "layers" | "maps"> &
  Omit<RuntimeAttentionMapDescriptor, "mapUrl"> & {
    values: number[];
  };

export type RuntimeInfluenceChunk = {
  chunk: number;
  tokenStart: number;
  tokenEnd: number;
  meanAbs: number;
  l2: number;
  cosineFull: number;
  deltaL2: number;
  spatialDelta: number[];
};

export type RuntimeInfluenceStep = {
  step: number;
  width: number;
  height: number;
  cfgDeltaL2: number;
  cfgCosine: number;
  chunks: RuntimeInfluenceChunk[];
};

export type RuntimeInfluenceAvailable = {
  available: true;
  runId: string;
  contractVersion: "h6-conditioning-v1";
  kind: "conditioning-influence";
  truth: "observed";
  source: "debug-unet" | "diffusers-unet";
  method: "chunk-vs-full-guided" | "identity-ablation-guided" | "visual-reference-ablation-guided";
  chunkSize: 77;
  totalChunks: number;
  capturedChunks: number;
  steps: RuntimeInfluenceStep[];
};

export type RuntimeInfluence = RuntimeInfluenceAvailable | RuntimeAttentionUnavailable;

export type RuntimeSelfAttentionMapDescriptor = Omit<RuntimeAttentionMapDescriptor, "tokenSlot"> & {
  queryIndex: number;
  queryX: number;
  queryY: number;
};

export type RuntimeSelfAttentionIndexAvailable = {
  available: true;
  runId: string;
  contractVersion: "h7-self-attention-v1";
  kind: "self-attention";
  truth: "observed";
  source: "debug-unet" | "diffusers-unet";
  layers: RuntimeAttentionLayer[];
  maps: RuntimeSelfAttentionMapDescriptor[];
};

export type RuntimeSelfAttentionIndex = RuntimeSelfAttentionIndexAvailable | RuntimeAttentionUnavailable;
export type RuntimeSelfAttentionMap = Omit<RuntimeSelfAttentionIndexAvailable, "layers" | "maps"> &
  Omit<RuntimeSelfAttentionMapDescriptor, "mapUrl"> & { values: number[] };
export type RuntimeSelfAttentionMapResponse = RuntimeSelfAttentionMap | RuntimeAttentionUnavailable;

export type RuntimeTrace = {
  available?: true;
  truth?: TruthLevel;
  runId: string;
  totalTimeMs: number;
  nodes: RuntimeNode[];
  events?: RuntimeTraceEvent[];
  latentPreviewFrames?: RuntimeTracePreviewFrame[];
  latentTelemetry?: RuntimeLatentTelemetry[];
  evidence?: {
    truth?: "observed";
    modelId?: string;
    outputPath?: string;
    metadataPath?: string;
    steps?: number;
    cfg?: number;
    samplingMethod?: string;
    scheduler?: string;
    backend?: string;
    backendTruth?: "observed";
    peakVramMiB?: number | null;
    peakRamBytes?: number | null;
    wrapperLogPath?: string;
  };
};

export type CurrentHardwareSnapshot = HardwareSnapshot & {
  backend?: string;
  backendTruth?: "derived";
};

export type RuntimeTraceUnavailable = {
  available: false;
  runId: string;
  message: string;
  truth: "unavailable";
};

export type RuntimeTraceResponse = RuntimeTrace | RuntimeTraceUnavailable;

export type RuntimeTraceSummary = {
  runId: string;
  totalTimeMs: number;
  modelId?: string;
  steps?: number;
  backend?: string;
  hasAttention: boolean;
  // Older servers omit these flags; absence is never evidence of availability.
  hasInfluence?: boolean;
  hasSelfAttention?: boolean;
  hasLatent: boolean;
  modifiedAt: string;
  truth: "observed";
};

export function isRuntimeTrace(value: RuntimeTraceResponse): value is RuntimeTrace {
  return value.available !== false && Array.isArray(value.nodes);
}

export type ResearchStatus = {
  available: boolean;
  message: string;
  truth: TruthLevel;
};

export type RuntimeCapability = {
  available: boolean;
  truth: TruthLevel;
  message?: string;
};

export type RuntimeCapabilities = {
  nativeGeneration: RuntimeCapability;
  processTrace: RuntimeCapability;
  latentTrace: RuntimeCapability;
  semanticExperiments: RuntimeCapability;
  attention: RuntimeCapability;
  conditioningInfluence?: RuntimeCapability;
  selfAttention?: RuntimeCapability;
};
