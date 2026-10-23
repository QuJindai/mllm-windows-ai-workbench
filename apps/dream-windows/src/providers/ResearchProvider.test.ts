import { afterEach, describe, expect, it, vi } from "vitest";
import { DreamHttpProvider } from "./DreamHttpProvider";
import { MockDreamProvider } from "./MockDreamProvider";
import { influenceArtifact, selfIndexArtifact, selfMapArtifact } from "../test/research-artifacts";

afterEach(() => vi.unstubAllGlobals());
function respond(body: unknown, status = 200) {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("research artifact provider contracts", () => {
  it("maps independent installed H6 and self capabilities without inferring them from cross", async () => {
    respond({
      conditioning_influence: { available: true, truth: "observed" },
      self_attention: { available: true, truth: "observed" },
      attention: { available: false, truth: "unavailable" },
    });
    await expect(new DreamHttpProvider().getCapabilities()).resolves.toMatchObject({
      conditioningInfluence: { available: true, truth: "observed" },
      selfAttention: { available: true, truth: "observed" },
      attention: { available: false },
    });
    respond({ attention: { available: true, truth: "observed" } });
    await expect(new DreamHttpProvider().getCapabilities()).resolves.toMatchObject({
      conditioningInfluence: { available: false, truth: "unavailable" },
      selfAttention: { available: false, truth: "unavailable" },
    });
  });

  it("reads H6 raw metrics through the encoded influence endpoint", async () => {
    const fetcher = respond({ ...influenceArtifact, runId: "run /6" });
    const result = await new DreamHttpProvider().getInfluence("run /6");
    expect(result).toMatchObject({ available: true, method: "chunk-vs-full-guided", steps: [{ cfgDeltaL2: 1.25 }, { cfgDeltaL2: 0 }] });
    expect(fetcher).toHaveBeenCalledWith("/api/traces/run%20%2F6/influence", expect.objectContaining({ method: "GET" }));
  });

  it("reads self index and only the requested raw probability map", async () => {
    const fetcher = respond(selfIndexArtifact);
    const provider = new DreamHttpProvider();
    await expect(provider.getSelfAttentionIndex("run-self")).resolves.toMatchObject({ available: true, maps: [{ queryIndex: 0 }, { queryIndex: 3 }, { queryIndex: 3 }] });
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify(selfMapArtifact()), { status: 200 }));
    await expect(provider.getSelfAttentionMap("run-self", "self-center")).resolves.toMatchObject({ available: true, values: [0.1, 0.2, 0.3, 0.4] });
    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/traces/run-self/self-attention", expect.objectContaining({ method: "GET" }));
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/traces/run-self/self-attention/maps/self-center", expect.objectContaining({ method: "GET" }));
  });

  it("preserves an unavailable artifact reason and has no mock fallback", async () => {
    const unavailable = { available: false, runId: "missing", truth: "unavailable", message: "当前运行未采集条件影响" };
    respond(unavailable);
    await expect(new DreamHttpProvider().getInfluence("missing")).resolves.toEqual(unavailable);
    await expect(new MockDreamProvider().getInfluence("missing")).resolves.toMatchObject({ available: false, truth: "unavailable" });
    await expect(new MockDreamProvider().getSelfAttentionIndex("missing")).resolves.toMatchObject({ available: false, truth: "unavailable" });
    await expect(new MockDreamProvider().getSelfAttentionMap("missing", "no-map")).resolves.toMatchObject({ available: false, truth: "unavailable" });
  });

  it("keeps an undeployed endpoint unavailable", async () => {
    respond({ detail: "Not Found" }, 404);
    await expect(new DreamHttpProvider().getInfluence("run-h6")).resolves.toMatchObject({ available: false, truth: "unavailable", message: expect.stringMatching(/接口.*不可用/) });
  });

  it("preserves exact zero deltas for a single chunk", async () => {
    respond({ ...influenceArtifact, totalChunks: 1, capturedChunks: 1, steps: [{ ...influenceArtifact.steps[1], chunks: [influenceArtifact.steps[1].chunks[0]] }] });
    await expect(new DreamHttpProvider().getInfluence("run-h6")).resolves.toMatchObject({ available: true, steps: [{ cfgDeltaL2: 0, chunks: [{ deltaL2: 0, spatialDelta: [0, 0, 0, 0] }] }] });
  });

  it("rejects a single chunk artifact claiming a nonzero difference from full context", async () => {
    respond({ ...influenceArtifact, totalChunks: 1, capturedChunks: 1, steps: [{ ...influenceArtifact.steps[0], chunks: [influenceArtifact.steps[0].chunks[0]] }] });
    await expect(new DreamHttpProvider().getInfluence("run-h6")).resolves.toMatchObject({ available: false, truth: "unavailable" });
  });

  it.each([
    ["wrong provenance", { ...influenceArtifact, truth: "demo" }],
    ["wrong run", { ...influenceArtifact, runId: "another-run" }],
    ["wrong method", { ...influenceArtifact, method: "chunk-average" }],
    ["too many steps", { ...influenceArtifact, steps: Array.from({ length: 6 }, (_, step) => ({ ...influenceArtifact.steps[0], step })) }],
    ["too many chunks", { ...influenceArtifact, capturedChunks: 4 }],
    ["oversize map", { ...influenceArtifact, steps: [{ ...influenceArtifact.steps[0], width: 129 }] }],
    ["invalid cosine", { ...influenceArtifact, steps: [{ ...influenceArtifact.steps[0], cfgCosine: 1.01 }] }],
    ["nonfinite metric", { ...influenceArtifact, steps: [{ ...influenceArtifact.steps[0], cfgDeltaL2: Infinity }] }],
    ["missing values", { ...influenceArtifact, steps: [{ ...influenceArtifact.steps[0], chunks: [{ ...influenceArtifact.steps[0].chunks[0], spatialDelta: [0] }] }] }],
    ["negative map", { ...influenceArtifact, capturedChunks: 1, steps: [{ ...influenceArtifact.steps[0], chunks: [{ ...influenceArtifact.steps[0].chunks[0], spatialDelta: [0, -1, 0, 0] }] }] }],
  ])("rejects H6 %s", async (_name, artifact) => {
    respond(artifact);
    await expect(new DreamHttpProvider().getInfluence("run-h6")).resolves.toMatchObject({ available: false, truth: "unavailable", message: expect.stringContaining("无效") });
  });

  it.each([
    ["oversize index", { ...selfIndexArtifact, maps: Array(513).fill(selfIndexArtifact.maps[0]) }],
    ["out of grid anchor", { ...selfIndexArtifact, maps: [{ ...selfIndexArtifact.maps[0], queryX: 2 }] }],
    ["mismatched query index", { ...selfIndexArtifact, maps: [{ ...selfIndexArtifact.maps[0], queryIndex: 3 }] }],
    ["unknown layer", { ...selfIndexArtifact, maps: [{ ...selfIndexArtifact.maps[0], layerId: "unknown" }] }],
    ["nonfinite statistics", { ...selfIndexArtifact, maps: [{ ...selfIndexArtifact.maps[0], entropy: NaN }] }],
  ])("rejects self %s", async (_name, artifact) => {
    respond(artifact);
    await expect(new DreamHttpProvider().getSelfAttentionIndex("run-self")).resolves.toMatchObject({ available: false, truth: "unavailable" });
  });

  it.each([
    ["probability out of range", { ...selfMapArtifact(), values: [0, 0.2, 0.3, 1.1] }],
    ["wrong map identity", { ...selfMapArtifact(), id: "other" }],
    ["nonfinite probability", { ...selfMapArtifact(), values: [0, 0.2, NaN, 0.4] }],
    ["wrong grid size", { ...selfMapArtifact(), values: [0.1] }],
  ])("rejects self map %s", async (_name, artifact) => {
    respond(artifact);
    await expect(new DreamHttpProvider().getSelfAttentionMap("run-self", "self-center")).resolves.toMatchObject({ available: false, truth: "unavailable" });
  });
});
