// Contract fixtures for tests only; these are never used as application evidence.
export const influenceArtifact = {
  available: true, runId: "run-h6", contractVersion: "h6-conditioning-v1",
  kind: "conditioning-influence", truth: "observed", source: "debug-unet",
  method: "chunk-vs-full-guided", chunkSize: 77, totalChunks: 2, capturedChunks: 2,
  steps: [
    { step: 0, width: 2, height: 2, cfgDeltaL2: 1.25, cfgCosine: 0.8, chunks: [
      { chunk: 0, tokenStart: 0, tokenEnd: 77, meanAbs: 0.125, l2: 2.5, cosineFull: 0.9, deltaL2: 0.5, spatialDelta: [0.001, 0.002, 0.003, 0.004] },
      { chunk: 1, tokenStart: 77, tokenEnd: 154, meanAbs: 0.25, l2: 3.5, cosineFull: -0.2, deltaL2: 0.75, spatialDelta: [0.01, 0.02, 0.03, 0.04] },
    ] },
    { step: 4, width: 2, height: 2, cfgDeltaL2: 0, cfgCosine: 1, chunks: [
      { chunk: 0, tokenStart: 0, tokenEnd: 77, meanAbs: 0.2, l2: 3, cosineFull: 1, deltaL2: 0, spatialDelta: [0, 0, 0, 0] },
      { chunk: 1, tokenStart: 77, tokenEnd: 154, meanAbs: 0.3, l2: 4, cosineFull: 0.95, deltaL2: 0.1, spatialDelta: [0.01, 0.02, 0.01, 0.02] },
    ] },
  ],
} as const;

export const selfIndexArtifact = {
  available: true, runId: "run-self", contractVersion: "h7-self-attention-v1",
  kind: "self-attention", truth: "observed", source: "debug-unet",
  layers: [{ id: "mid-1", stage: "mid", label: "中间层 1" }],
  maps: [
    { id: "self-center", step: 0, layerId: "mid-1", queryIndex: 0, queryX: 0, queryY: 0, width: 2, height: 2, entropy: 1.2, peak: 0.4, coverage: 0.75, mapUrl: "/api/traces/run-self/self-attention/maps/self-center" },
    { id: "self-right", step: 0, layerId: "mid-1", queryIndex: 3, queryX: 1, queryY: 1, width: 2, height: 2, entropy: 1.386294, peak: 0.25, coverage: 1, mapUrl: "/api/traces/run-self/self-attention/maps/self-right" },
    { id: "self-later", step: 4, layerId: "mid-1", queryIndex: 3, queryX: 1, queryY: 1, width: 2, height: 2, entropy: 0.5, peak: 0.7, coverage: 0.25, mapUrl: "/api/traces/run-self/self-attention/maps/self-later" },
  ],
} as const;

export function selfMapArtifact(id = "self-center") {
  const descriptor = selfIndexArtifact.maps.find((entry) => entry.id === id)!;
  const { mapUrl: _mapUrl, ...identity } = descriptor;
  return {
    available: true, runId: "run-self", contractVersion: "h7-self-attention-v1",
    kind: "self-attention", truth: "observed", source: "debug-unet", ...identity,
    values: id === "self-right" ? [0.25, 0.25, 0.25, 0.25] : id === "self-later" ? [0.1, 0.1, 0.1, 0.7] : [0.1, 0.2, 0.3, 0.4],
  };
}
