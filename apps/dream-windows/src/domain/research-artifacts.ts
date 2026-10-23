import type { RuntimeInfluenceAvailable, RuntimeSelfAttentionIndexAvailable, RuntimeSelfAttentionMap } from "./trace";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue => typeof value === "object" && value !== null && !Array.isArray(value);
const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max;
const finite = (value: unknown, min = -Infinity, max = Infinity): value is number => typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 512;
const boundedArray = (value: unknown, max: number): value is unknown[] => Array.isArray(value) && value.length > 0 && value.length <= max;
const unique = (values: unknown[]) => new Set(values).size === values.length;
const grid = (value: RecordValue) => integer(value.width, 1, 128) && integer(value.height, 1, 128);
const marker = (value: RecordValue, runId: string, contract: string, kind: string) => value.available === true && value.runId === runId && value.contractVersion === contract && value.kind === kind && value.truth === "observed" && ["debug-unet", "diffusers-unet"].includes(String(value.source));

export function isInfluenceArtifact(value: unknown, runId: string): value is RuntimeInfluenceAvailable {
  if (!record(value)) return false;
  const identity = value.source === "diffusers-unet";
  const validMethod = identity ? ["identity-ablation-guided", "visual-reference-ablation-guided"].includes(String(value.method)) : value.method === "chunk-vs-full-guided";
  if (!marker(value, runId, "h6-conditioning-v1", "conditioning-influence") || !validMethod || value.chunkSize !== 77 || !integer(value.totalChunks, 1) || !integer(value.capturedChunks, 1, Math.min(3, value.totalChunks)) || !boundedArray(value.steps, identity ? 12 : 5)) return false;
  if (identity && (value.totalChunks !== 1 || value.capturedChunks !== 1)) return false;
  const totalChunks = value.totalChunks;
  const capturedChunks = value.capturedChunks;
  if (!value.steps.every((step) => {
    if (!record(step) || !integer(step.step) || !grid(step) || !finite(step.cfgDeltaL2, 0) || !finite(step.cfgCosine, -1, 1) || !boundedArray(step.chunks, 3) || step.chunks.length !== capturedChunks) return false;
    const size = (step.width as number) * (step.height as number);
    return step.chunks.every((chunk) => {
      if (!record(chunk) || !integer(chunk.chunk, 0, totalChunks - 1) || !integer(chunk.tokenStart) || !integer(chunk.tokenEnd, chunk.tokenStart) || !finite(chunk.meanAbs, 0) || !finite(chunk.l2, 0) || !finite(chunk.cosineFull, -1, 1) || !finite(chunk.deltaL2, 0) || !Array.isArray(chunk.spatialDelta) || chunk.spatialDelta.length !== size || !chunk.spatialDelta.every((entry) => finite(entry, 0))) return false;
      return identity || totalChunks !== 1 || (chunk.deltaL2 === 0 && chunk.spatialDelta.every((entry) => entry === 0));
    }) && unique(step.chunks.map((chunk) => (chunk as RecordValue).chunk));
  })) return false;
  return unique(value.steps.map((step) => (step as RecordValue).step));
}

function selfDescriptor(value: unknown): value is RecordValue {
  if (!record(value) || !text(value.id) || !text(value.layerId) || !integer(value.step) || !grid(value)) return false;
  const width = value.width as number;
  const height = value.height as number;
  return integer(value.queryX, 0, width - 1) && integer(value.queryY, 0, height - 1) && integer(value.queryIndex, 0, width * height - 1) && value.queryIndex === value.queryY * width + value.queryX && finite(value.entropy, 0) && finite(value.peak, 0, 1) && finite(value.coverage, 0, 1);
}

export function isSelfAttentionIndexArtifact(value: unknown, runId: string): value is RuntimeSelfAttentionIndexAvailable {
  if (!record(value)) return false;
  const identity = value.source === "diffusers-unet";
  if (!marker(value, runId, "h7-self-attention-v1", "self-attention") || !boundedArray(value.layers, identity ? 32 : 3) || !boundedArray(value.maps, identity ? 4000 : 512)) return false;
  if (!value.layers.every((layer) => record(layer) && text(layer.id) && text(layer.label) && ["down", "mid", "up"].includes(String(layer.stage)))) return false;
  const layers = value.layers as RecordValue[];
  if (!unique(layers.map((layer) => layer.id)) || !value.maps.every((map) => selfDescriptor(map) && text(map.mapUrl) && layers.some((layer) => layer.id === map.layerId))) return false;
  const maps = value.maps as RecordValue[];
  return unique(maps.map((map) => map.id)) && unique(maps.map((map) => `${map.step}/${map.layerId}/${map.queryIndex}`)) && new Set(maps.map((map) => map.step)).size <= (identity ? 12 : 5) && layers.every((layer) => {
    const entries = maps.filter((map) => map.layerId === layer.id);
    return new Set(entries.map((map) => map.queryIndex)).size <= 9 && new Set(entries.map((map) => `${map.width}/${map.height}`)).size <= 1;
  });
}

export function isSelfAttentionMapArtifact(value: unknown, runId: string, mapId: string): value is RuntimeSelfAttentionMap {
  return selfDescriptor(value) && marker(value, runId, "h7-self-attention-v1", "self-attention") && value.id === mapId && Array.isArray(value.values) && value.values.length === (value.width as number) * (value.height as number) && value.values.every((entry) => finite(entry, 0, 1));
}
