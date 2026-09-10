import { afterEach, describe, expect, it, vi } from "vitest";
import type { GenerationRequest } from "../domain/generation";
import type { WorkspaceEntry } from "../domain/settings";
import { DreamHttpProvider } from "./DreamHttpProvider";

afterEach(() => vi.unstubAllGlobals());

describe("DreamHttpProvider", () => {
  it("reads live hardware and models from the browser API", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ gpuName: "Live GPU", cudaReady: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "model", displayName: "Live Model" }]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const provider = new DreamHttpProvider();

    expect((await provider.getHardware()).gpuName).toBe("Live GPU");
    expect((await provider.listModels())[0].displayName).toBe("Live Model");
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/hardware", expect.objectContaining({ method: "GET" }));
  });

  it("submits a generation request and returns the backend job handle", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "job-1", state: "queued" }), { status: 200 })));
    const request: GenerationRequest = { prompt: "lake", negativePrompt: "blur", modelId: "model", width: 256, height: 256, steps: 20, cfg: 7.0, samplingMethod: "dpm++2m", scheduler: "karras", seed: 1, fusionMode: "none", traceLevel: "basic" };

    await expect(new DreamHttpProvider().generate(request)).resolves.toEqual({ id: "job-1" });
  });

  it("surfaces the backend error code when an API call fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "MODEL_FILE_MISSING", message: "model missing" }), { status: 503 })));

    await expect(new DreamHttpProvider().listModels()).rejects.toThrow("MODEL_FILE_MISSING: model missing");
  });

  it("opens a fixed workspace entry through the local backend", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ opened: true, entry: "models", path: "E:\\Dream\\models" }), { status: 200 })));
    const entry: WorkspaceEntry = "models";

    await expect(new DreamHttpProvider().openWorkspace(entry)).resolves.toMatchObject({ opened: true, entry });
  });

  it("exposes capability truth and cancellation through the local backend", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ nativeGeneration: { available: true, truth: "observed" } }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "job-1", state: "cancelled", progress: 0 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const provider = new DreamHttpProvider();

    await expect(provider.getCapabilities()).resolves.toMatchObject({ nativeGeneration: { available: true } });
    await expect(provider.cancelJob("job-1")).resolves.toMatchObject({ state: "cancelled" });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/jobs/job-1/cancel", expect.objectContaining({ method: "POST" }));
  });

  it("normalizes the backend snake_case capability contract for the UI", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      native_generation: { available: true, truth: "observed" },
      process_trace: { available: true, truth: "derived" },
      latent_trace: { available: true, truth: "observed", message: "native latent telemetry ready" },
      semantic_experiments: { available: true, truth: "observed" },
      attention: { available: false, truth: "unavailable", message: "attention tensors are not exported" },
    }), { status: 200 })));

    const capabilities = await new DreamHttpProvider().getCapabilities();

    expect(capabilities.latentTrace).toEqual({ available: true, truth: "observed", message: "native latent telemetry ready" });
    expect(capabilities.attention).toEqual({ available: false, truth: "unavailable", message: "attention tensors are not exported" });
  });

  it("does not expose demo-only backend data as an H7 attention capability", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      native_generation: { available: true, truth: "observed" },
      process_trace: { available: true, truth: "derived" },
      latent_trace: { available: true, truth: "observed" },
      semantic_experiments: { available: true, truth: "observed" },
      attention: { available: true, truth: "demo", message: "fixture only" },
    }), { status: 200 })));

    const capabilities = await new DreamHttpProvider().getCapabilities();

    expect(capabilities.attention).toEqual({ available: false, truth: "unavailable", message: "fixture only" });
  });

  it("posts and reads a semantic experiment identity", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "experiment-1", kind: "fusion", seed: 42, lockedFields: ["seed", "modelId"], variants: [], status: "queued" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "experiment-1", kind: "fusion", seed: 42, lockedFields: ["seed", "modelId"], variants: [], status: "running" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const provider = new DreamHttpProvider();

    await expect(provider.runExperiment({
      kind: "fusion",
      seed: 42,
      modelId: "model",
      prompt: "a mountain lake",
      negativePrompt: "blur",
      steps: 20,
      cfg: 7,
    })).resolves.toMatchObject({ id: "experiment-1", seed: 42 });
    await expect(provider.getExperiment("experiment-1")).resolves.toMatchObject({ id: "experiment-1", status: "running" });
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/experiments", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        kind: "fusion",
        seed: 42,
        modelId: "model",
        prompt: "a mountain lake",
        negativePrompt: "blur",
        steps: 20,
        cfg: 7,
      }),
    }));
  });

  it("loads an H7 attention index and only the selected observed map", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        available: true,
        runId: "run-h7",
        contractVersion: "h7-attention-v1",
        kind: "cross-attention",
        truth: "observed",
        source: "debug-unet",
        tokens: [{ slot: 1, tokenId: 320, text: "lake", chunk: 0, weight: 1 }],
        layers: [{ id: "mid-1", stage: "mid", label: "Mid 1" }],
        maps: [{ id: "map-1", step: 0, layerId: "mid-1", tokenSlot: 1, width: 2, height: 2, entropy: 0.7, peak: 0.8, coverage: 0.2, mapUrl: "/api/traces/run-h7/attention/maps/map-1" }],
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        available: true,
        runId: "run-h7",
        contractVersion: "h7-attention-v1",
        kind: "cross-attention",
        truth: "observed",
        source: "debug-unet",
        id: "map-1",
        step: 0,
        layerId: "mid-1",
        tokenSlot: 1,
        width: 2,
        height: 2,
        entropy: 0.7,
        peak: 0.8,
        coverage: 0.2,
        values: [0, 0.25, 0.5, 1],
      }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const provider = new DreamHttpProvider();

    await expect(provider.getAttentionIndex("run-h7")).resolves.toMatchObject({ available: true, source: "debug-unet" });
    await expect(provider.getAttentionMap("run-h7", "map-1")).resolves.toMatchObject({ values: [0, 0.25, 0.5, 1] });
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/traces/run-h7/attention", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/traces/run-h7/attention/maps/map-1", expect.objectContaining({ method: "GET" }));
  });

  it("lists selectable runtime trace summaries", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([
      { runId: "run-new", totalTimeMs: 12000, modelId: "model-a", steps: 20, backend: "CUDA", hasAttention: false, hasLatent: true, modifiedAt: "2026-09-09T12:00:00+00:00", truth: "observed" },
      { runId: "run-h7", totalTimeMs: 24000, modelId: "model-b", steps: 28, backend: "CUDA", hasAttention: true, hasLatent: false, modifiedAt: "2026-09-09T11:00:00+00:00", truth: "observed" },
    ]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(new DreamHttpProvider().listRuntimeTraces()).resolves.toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/traces", expect.objectContaining({ method: "GET" }));
  });
});
