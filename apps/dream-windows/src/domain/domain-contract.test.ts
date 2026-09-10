import { expectTypeOf, vi } from "vitest";
import { MockDreamProvider } from "../providers/MockDreamProvider";
import type { ExperimentRequest } from "./experiment";
import type { GenerationBatch, GenerationBatchItem, GenerationRequest } from "./generation";

const request: GenerationRequest = {
  prompt: "a quiet mountain lake at sunrise",
  negativePrompt: "blurry, low quality",
  modelId: "cyberrealistic-v10-dmd2",
  width: 832,
  height: 1216,
  steps: 20,
  cfg: 7.0,
  samplingMethod: "dpm++2m",
  scheduler: "karras",
  seed: 20260906,
  fusionMode: "off",
  traceLevel: "basic",
};

const legacyRequest: GenerationRequest = {
  prompt: "legacy request",
  negativePrompt: "",
  modelId: "cyberrealistic-v10-dmd2",
  width: 512,
  height: 512,
  steps: 8,
  cfg: 1.2,
  seed: 7,
  fusionMode: "off",
  traceLevel: "basic",
};

const experimentRequest: ExperimentRequest = {
  kind: "fusion",
  seed: 42,
  modelId: request.modelId,
  prompt: request.prompt,
  negativePrompt: request.negativePrompt,
  steps: request.steps,
  cfg: request.cfg,
};

describe("typed Dream provider contract", () => {
  it("keeps request construction without sampler fields source-compatible", () => {
    expect(legacyRequest).not.toHaveProperty("samplingMethod");
    expect(legacyRequest).not.toHaveProperty("scheduler");
  });

  it("shares the complete semantic experiment request contract", () => {
    expectTypeOf<ExperimentRequest["prompt"]>().toEqualTypeOf<string>();
    expect(experimentRequest).toEqual({
      kind: "fusion",
      seed: 42,
      modelId: "cyberrealistic-v10-dmd2",
      prompt: "a quiet mountain lake at sunrise",
      negativePrompt: "blurry, low quality",
      steps: 20,
      cfg: 7,
    });
  });

  it("represents a generation batch as ordered queue items", () => {
    const item: GenerationBatchItem = {
      id: "batch-item-1",
      request,
      state: "queued",
      progress: 0,
      message: "waiting",
    };
    const batch: GenerationBatch = [item];

    expect(batch).toEqual([item]);
  });

  it("returns the local hardware and verified E-drive model fixture", async () => {
    const provider = new MockDreamProvider();
    const hardware = await provider.getHardware();
    const models = await provider.listModels();
    const history = await provider.listHistory({ page: 1, pageSize: 12 });

    expect(hardware.gpuName).toContain("RTX 1000 Ada");
    expect(hardware.vramTotalMiB).toBe(6141);
    expect(hardware.ramTotalBytes).toBeGreaterThan(60_000_000_000);
    expect(models[0]).toMatchObject({
      id: "cyberrealistic-xl-v10-standard",
      architecture: "SDXL",
      verified: true,
    });
    expect(models[0].path.toLowerCase()).toContain("e:\\dream");
    expect(history.items.length).toBeGreaterThan(2);
    expect(history.items[1].id).not.toBe(history.items[0].id);
  });

  it("labels fixed mock runtime trace values as demo or derived, never observed", async () => {
    const trace = await new MockDreamProvider().getRuntimeTrace("latest");

    expect(trace.truth).toBe("demo");
    expect(trace.nodes.filter((node) => node.truth === "observed")).toEqual([]);
    expect(trace.nodes.filter((node) => node.truth === "demo").map((node) => node.id)).toEqual(["prompt", "unet"]);
    expect(trace.nodes.filter((node) => node.truth === "demo").every((node) => node.expectedCallsTruth === "derived")).toBe(true);
    expect(trace.nodes.filter((node) => node.truth === "demo").every((node) => node.observedCalls === undefined)).toBe(true);
  });

  it("reports generation phases over time instead of injecting a result immediately", async () => {
    const provider = new MockDreamProvider();
    const handle = await provider.generate(request);
    const first = await provider.getJob(handle.id);

    expect(first.state).toBe("queued");
    await new Promise((resolve) => setTimeout(resolve, 160));
    const middle = await provider.getJob(handle.id);
    expect(["preparing", "sampling"]).toContain(middle.state);
    await new Promise((resolve) => setTimeout(resolve, 500));
    const complete = await provider.getJob(handle.id);
    expect(complete.state).toBe("complete");
    expect(complete.result?.truth).toBe("demo");
  });

  it("keeps a cancelled mock job cancelled when it is polled again", async () => {
    const provider = new MockDreamProvider();
    const handle = await provider.generate(request);

    await expect(provider.cancelJob(handle.id)).resolves.toMatchObject({ state: "cancelled" });
    await expect(provider.getJob(handle.id)).resolves.toMatchObject({ state: "cancelled" });
  });

  it("returns truthful prompt-level mock variants without invented metrics", async () => {
    const provider = new MockDreamProvider();
    const submitted = await provider.runExperiment({ kind: "fusion", seed: 42, modelId: request.modelId, prompt: request.prompt });

    expect(submitted).toMatchObject({ seed: 42, status: "complete" });
    expect(submitted.variants).toHaveLength(4);
    expect(submitted.variants.map((variant) => variant.label)).toEqual([
      "完整提示词（控制组）",
      "平衡描述改写",
      "仅首段提示词",
      "重点描述改写",
    ]);
    expect(submitted.variants.map((variant) => variant.modelId)).toEqual(Array(4).fill(request.modelId));
    expect(submitted.variants.every((variant) => !("metric" in variant))).toBe(true);
    expect(submitted.lockedFields).toEqual(["seed", "modelId"]);
    await expect(provider.getExperiment(submitted.id)).resolves.toEqual(submitted);
  });

  it("keeps model identity variable for model comparison and includes the requested model", async () => {
    const provider = new MockDreamProvider();
    const submitted = await provider.runExperiment({ kind: "model", seed: 42, modelId: "dream-illustration-xl", prompt: request.prompt });

    expect(submitted.lockedFields).toEqual(["seed"]);
    expect(submitted.variants[0].modelId).toBe("dream-illustration-xl");
    expect(submitted.variants.map((variant) => variant.modelId)).toContain("dream-illustration-xl");
  });

  it("keeps mock experiment fixtures independent of wall-clock time", async () => {
    const now = vi.spyOn(Date, "now");
    try {
      now.mockReturnValueOnce(1_000);
      const first = await new MockDreamProvider().runExperiment({ kind: "fusion", seed: 42, modelId: request.modelId, prompt: request.prompt });
      now.mockReturnValueOnce(2_000);
      const second = await new MockDreamProvider().runExperiment({ kind: "fusion", seed: 42, modelId: request.modelId, prompt: request.prompt });

      expect(second).toEqual(first);
    } finally {
      now.mockRestore();
    }
  });
});
