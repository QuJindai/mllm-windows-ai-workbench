import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MicroscopePage } from "./MicroscopePage";
import { DreamProviderContext } from "../providers";
import { DreamHttpProvider } from "../../providers/DreamHttpProvider";
import { influenceArtifact, selfIndexArtifact, selfMapArtifact } from "../../test/research-artifacts";
import hardware from "../../fixtures/hardware.json";

afterEach(() => vi.unstubAllGlobals());

const visual = "cyberrealistic-xl-plus-face";
const faceid = "illustrious-xl-v2.0-faceid";
const missing = (runId: string) => ({ available: false, runId, truth: "unavailable", message: "No validated native H7 attention trace is available" });
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function job(id: string, modelId: string, traceLevel: string, research: Record<string, unknown> = {}) {
  return { id, state: "complete", progress: 100, message: "生成完成", error: null,
    request: { modelId, referenceId: "ref-test", faceIndex: 0, prompt: "lake", negativePrompt: "", seed: 42,
      width: 768, height: 768, steps: 30, cfg: 5, identityStrength: 0.8, structureStrength: 0, faceLoraStrength: 0,
      facePolish: false, faceRestoreStrength: 1, traceLevel, researchCoverage: "representative" },
    result: { imageUrl: `/api/history/${id}/image`, metadata: { research: { runId: id, traceLevel, h6: false, h7: false, ...research } } } };
}
function trace(runId: string, modelId: string) {
  return { available: true, truth: "observed", runId, totalTimeMs: 1000, nodes: [],
    evidence: { truth: "observed", modelId, backend: "diffusers-unet", cfg: 5, steps: 30 } };
}
function summary(runId: string, modelId: string, recorded = false) {
  return { runId, modelId, totalTimeMs: 1000, hasAttention: recorded, hasInfluence: recorded,
    hasSelfAttention: recorded, hasLatent: true, modifiedAt: "2026-10-11T00:00:00Z", truth: "observed" };
}
type Route = unknown | (() => Promise<Response>);
function setup(modelId = visual, traceLevel = "basic", overrides: Record<string, Route> = {}) {
  const runId = "identity-current";
  const routes: Record<string, Route> = {
    "/api/hardware": hardware,
    "/api/capabilities": { attention: { available: true, truth: "observed", message: "生产能力已就绪" } },
    "/api/research/status": { available: true, truth: "observed", message: "研究引擎已就绪" },
    "/api/traces": [summary(runId, modelId)],
    "/api/traces/latest": trace(runId, modelId),
    [`/api/traces/${runId}`]: trace(runId, modelId),
    [`/api/identity/jobs/${runId}`]: job(runId, modelId, traceLevel),
    ...overrides,
  };
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    if (path in routes) return typeof routes[path] === "function" ? (routes[path] as () => Promise<Response>)() : response(routes[path]);
    if (/\/api\/traces\/[^/]+\/(attention|influence|self-attention)$/.test(path)) return response(missing(path.split("/")[3]));
    throw new Error(`Unexpected request: ${path}`);
  }));
  render(<DreamProviderContext.Provider value={new DreamHttpProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
}
async function open(view: string) {
  fireEvent.click(await screen.findByRole("tab", { name: view === "self" ? "H7 注意力" : view }));
  if (view === "self") fireEvent.click(screen.getByRole("tab", { name: "Self-attention 自注意力" }));
}
const enableAdvice = /请.*(?:生成页|人物创作).*启用|请在生成页选择 H6/;
function expectNoMaps() {
  expect(screen.queryByRole("img", { name: /热力图|实测空间差异|实测概率图/ })).not.toBeInTheDocument();
}

describe("Microscope route-specific capture guidance", () => {
  // Break: presenting old basic records as measured visual H6/H7 captures.
  it.each(["H7 注意力", "self", "语义", "专家", "条件影响"])("explains missing visual capture in %s with regeneration advice", async (view) => {
    setup();
    await open(view);
    expect((await screen.findAllByText(/本次视觉参考任务未启用/))[0]).toBeVisible();
    expect(screen.getByText(enableAdvice)).toBeVisible();
    expect(screen.queryByText(/能力和研究引擎已就绪/)).not.toBeInTheDocument();
    expect(screen.queryByText("生产能力已就绪")).not.toBeInTheDocument();
    expectNoMaps();
  });

  // Break: reporting every missing artifact as a route limitation or as a failed capture.
  it.each([["H7 注意力", "H7"], ["条件影响", "H6"], ["self", "H7"]])("offers FaceID enable advice only when %s was not enabled", async (view, level) => {
    setup(faceid);
    await open(view);
    expect((await screen.findAllByText(new RegExp(`本次任务未启用 ${level}`)))[0]).toBeVisible();
    expect(screen.getAllByText(/请在人物创作.*启用/)[0]).toBeVisible();
    expect(screen.queryByText(/采集失败/)).not.toBeInTheDocument();
    expectNoMaps();
  });

  it.each(["H7 注意力", "条件影响", "self"])("reports publication failure in %s without blaming disabled capture", async (view) => {
    setup(faceid, "h7", { "/api/identity/jobs/identity-current": job("identity-current", faceid, "h7", {
      status: "failed", error: { code: "IDENTITY_RESEARCH_PUBLICATION_FAILED" }, message: "研究产物发布失败，已保留生成图片和历史记录" }) });
    await open(view);
    expect((await screen.findAllByText(/采集失败.*发布失败/))[0]).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
    expect(screen.queryByText(/本次任务未启用/)).not.toBeInTheDocument();
    expectNoMaps();
  });

  it.each([
    ["basic", "条件影响", "H6"],
    ["basic", "H7 注意力", "H7"],
    ["basic", "self", "H7"],
    ["h6", "H7 注意力", "H7"],
    ["h6", "self", "H7"],
  ])("does not attribute %s publication failure to unrequested %s capture", async (traceLevel, view, level) => {
    setup(faceid, traceLevel, {
      "/api/identity/jobs/identity-current": job("identity-current", faceid, traceLevel, { status: "failed" }),
    });
    await open(view);
    expect((await screen.findAllByText(new RegExp(`本次任务未启用 ${level}`)))[0]).toBeVisible();
    expect(screen.getByText(/运行记录发布失败/)).toBeVisible();
    expect(screen.queryByText(new RegExp(`${level} 采集失败`))).not.toBeInTheDocument();
    expectNoMaps();
  });

  it.each(["H7 注意力", "语义", "专家"])("settles an explicit off job without a root trace as not enabled in %s", async view => {
    setup(faceid, "off", {
      "/api/traces/latest": { available: false, runId: "latest", truth: "unavailable", message: "No native runtime trace is available" },
      "/api/traces/identity-current": { available: false, runId: "identity-current", truth: "unavailable", message: "No native runtime trace is available" },
    });
    await open(view);
    fireEvent.change(screen.getByRole("combobox", { name: "选择运行记录" }), { target: { value: "identity-current" } });
    expect((await screen.findAllByText(/本次任务未启用 H7/))[0]).toBeVisible();
    expect(screen.queryByText(/正在核对本次任务/)).not.toBeInTheDocument();
    expectNoMaps();
  });

  it("keeps an enabled capture with missing artifacts distinct from disabled capture", async () => {
    setup(faceid, "h7");
    await open("H7 注意力");
    expect((await screen.findAllByText(/已启用 H7.*未取得有效/))[0]).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
    expect(screen.queryByText(/本次任务未启用|采集失败/)).not.toBeInTheDocument();
    expectNoMaps();
  });

  it.each([faceid, visual, "illustrious-xl-v2.0-plus-face"].flatMap(model =>
    ["H7 注意力", "条件影响", "self"].map(view => [model, view])))
  ("does not invent a capture setting for %s in %s when the historical job cannot be read", async (model, view) => {
    setup(model, "basic", { "/api/identity/jobs/identity-current": () => Promise.resolve(response({ message: "任务记录不存在" }, 404)) });
    await open(view);
    expect((await screen.findAllByText(/无法确认.*采集设置/))[0]).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
    expect(screen.queryByText(/本次(?:视觉参考)?任务未启用|采集失败/)).not.toBeInTheDocument();
  });

  it.each([faceid, visual, "illustrious-xl-v2.0-plus-face"].flatMap(model =>
    [["H7 注意力", "attention"], ["条件影响", "influence"], ["self", "self-attention"]]
      .map(([view, artifact]) => [model, view, artifact])))
  ("reports an index read failure for %s in %s separately from capture settings", async (model, view, artifact) => {
    setup(model, "basic", { [`/api/traces/identity-current/${artifact}`]: () => Promise.resolve(response({ message: "索引读取失败" }, 500)) });
    await open(view);
    expect((await screen.findAllByText(/读取失败/))[0]).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
    expect(screen.queryByText(/本次(?:视觉参考)?任务未启用/)).not.toBeInTheDocument();
    expectNoMaps();
  });

  it.each([faceid, visual, "illustrious-xl-v2.0-plus-face"])
  ("keeps a network error distinct from disabled capture for %s even without a localized error", async model => {
    setup(model, "basic", { "/api/traces/identity-current/attention": () => Promise.reject(new TypeError("Failed to fetch")) });
    await open("H7 注意力");
    expect((await screen.findAllByText(/读取失败/))[0]).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
    expect(screen.queryByText(/本次(?:视觉参考)?任务未启用/)).not.toBeInTheDocument();
  });

  it("offers the generation page only for a known native job with capture disabled", async () => {
    setup("dreamshaper-xl", "basic", {
      "/api/traces/latest": trace("job-native", "dreamshaper-xl"),
      "/api/traces": [summary("job-native", "dreamshaper-xl")],
      "/api/jobs/job-native": { ...job("job-native", "dreamshaper-xl", "basic"),
        request: { prompt: "lake", negativePrompt: "", modelId: "dreamshaper-xl", width: 768, height: 768, steps: 8, cfg: 2,
          seed: 42, fusionMode: "native", traceLevel: "basic" } },
    });
    await open("H7 注意力");
    expect((await screen.findAllByText(/本次任务未启用 H7.*请在生成页启用/))[0]).toBeVisible();
    expect(screen.queryByText(/请在人物创作/)).not.toBeInTheDocument();
    expectNoMaps();
  });

  it("does not recommend enablement for an unknown identity model", async () => {
    setup("future-identity-model");
    await open("H7 注意力");
    expect((await screen.findAllByText(/当前路线的采集能力尚未确认/))[0]).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
  });

  it("reads publication failure from the selected job even when publishing the root trace failed", async () => {
    setup(faceid, "h7", {
      "/api/traces/latest": { available: false, runId: "latest", truth: "unavailable", message: "No native runtime trace is available" },
      "/api/traces/identity-current": { available: false, runId: "identity-current", truth: "unavailable", message: "No native runtime trace is available" },
      "/api/identity/jobs/identity-current": job("identity-current", faceid, "h7", { status: "failed" }),
    });
    await open("H7 注意力");
    fireEvent.change(screen.getByRole("combobox", { name: "选择运行记录" }), { target: { value: "identity-current" } });
    expect((await screen.findAllByText(/采集失败.*发布失败/))[0]).toBeVisible();
    expectNoMaps();
  });

  it("refreshes the selected job evidence after a capture publication failure", async () => {
    let research: Record<string, unknown> = { status: "failed" };
    setup(faceid, "h7", { "/api/identity/jobs/identity-current": () => Promise.resolve(response(job("identity-current", faceid, "h7", research))) });
    await open("H7 注意力");
    expect((await screen.findAllByText(/采集失败.*发布失败/))[0]).toBeVisible();
    research = {};
    fireEvent.click(screen.getByRole("button", { name: "刷新记录" }));
    expect((await screen.findAllByText(/已启用 H7.*未取得有效/))[0]).toBeVisible();
    expect(screen.queryByText(/采集失败/)).not.toBeInTheDocument();
  });

  // Break: blocking archived tensors based on current route/global status or an unavailable job record.
  it.each(["条件影响", "self"])("uses the validated %s artifact without a second lookup replacing it with an empty state", async view => {
    let reads = 0;
    const artifact = view === "self" ? { ...selfIndexArtifact, runId: "identity-current", source: "diffusers-unet" }
      : { ...influenceArtifact, runId: "identity-current", source: "diffusers-unet", method: "identity-ablation-guided", totalChunks: 1, capturedChunks: 1,
          steps: influenceArtifact.steps.map(step => ({ ...step, chunks: [step.chunks[0]] })) };
    setup(faceid, "h7", {
      [`/api/traces/identity-current/${view === "self" ? "self-attention" : "influence"}`]: () => Promise.resolve(++reads === 1
        ? response(artifact) : response({ message: "索引读取失败" }, 500)),
      "/api/traces/identity-current/self-attention/maps/self-center": { ...selfMapArtifact(), runId: "identity-current", source: "diffusers-unet" },
    });
    await open(view);
    expect(await screen.findByRole("img", { name: /实测空间差异|实测概率图/ })).toBeVisible();
    expect(screen.queryByText(enableAdvice)).not.toBeInTheDocument();
  });

  it("switches from visual capture to historical FaceID cross, self and H6 maps and back", async () => {
    const old = "identity-faceid-history";
    const cross = { available: true, runId: old, contractVersion: "h7-attention-v1", kind: "cross-attention", truth: "observed", source: "diffusers-unet",
      tokens: [{ slot: 1, tokenId: 320, text: "lake", chunk: 0, weight: 1 }], layers: [{ id: "mid-1", stage: "mid", label: "Mid 1" }],
      maps: [{ id: "lake-mid", step: 0, layerId: "mid-1", tokenSlot: 1, width: 2, height: 2, entropy: .7, peak: .8, coverage: .2, mapUrl: `/api/traces/${old}/attention/maps/lake-mid` }] };
    setup(visual, "basic", {
      "/api/capabilities": {}, "/api/research/status": { available: false, truth: "unavailable", message: "研究引擎离线" },
      "/api/traces": [summary("identity-current", visual), summary(old, faceid, true)],
      [`/api/traces/${old}`]: trace(old, faceid),
      [`/api/identity/jobs/${old}`]: () => Promise.resolve(response({ message: "旧任务已归档" }, 404)),
      [`/api/traces/${old}/attention`]: cross,
      [`/api/traces/${old}/attention/maps/lake-mid`]: { available: true, runId: old, contractVersion: "h7-attention-v1", kind: "cross-attention", truth: "observed", source: "diffusers-unet", ...cross.maps[0], values: [0, .2, .5, .8] },
      [`/api/traces/${old}/self-attention`]: { ...selfIndexArtifact, runId: old, source: "diffusers-unet" },
      [`/api/traces/${old}/self-attention/maps/self-center`]: { ...selfMapArtifact(), runId: old, source: "diffusers-unet" },
      [`/api/traces/${old}/influence`]: { ...influenceArtifact, runId: old, source: "diffusers-unet", method: "identity-ablation-guided", totalChunks: 1, capturedChunks: 1,
        steps: influenceArtifact.steps.map(step => ({ ...step, chunks: [step.chunks[0]] })) },
    });
    await open("H7 注意力");
    expect((await screen.findAllByText(/本次视觉参考任务未启用/))[0]).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "选择最近的H7记录" }));
    expect(await screen.findByRole("img", { name: /lake.*注意力热力图/ })).toBeVisible();
    expect(screen.queryByText(/本次视觉参考任务未启用/)).not.toBeInTheDocument();
    await open("self");
    expect(await screen.findByRole("img", { name: /自注意力.*实测概率图/ })).toBeVisible();
    await open("条件影响");
    expect(await screen.findByRole("img", { name: /H6.*实测空间差异/ })).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "选择运行记录" }), { target: { value: "identity-current" } });
    expect((await screen.findAllByText(/本次视觉参考任务未启用/))[0]).toBeVisible();
    expectNoMaps();
    expect(screen.getByText(enableAdvice)).toBeVisible();
  });

  it("ignores a late job response after switching to the visual route", async () => {
    let resolveJob!: (value: Response) => void;
    const pending = new Promise<Response>(resolve => { resolveJob = resolve; });
    setup(faceid, "basic", {
      "/api/traces": [summary("identity-current", faceid), summary("identity-visual", visual)],
      "/api/identity/jobs/identity-current": () => pending,
      "/api/traces/identity-visual": trace("identity-visual", visual),
      "/api/identity/jobs/identity-visual": job("identity-visual", visual, "basic"),
    });
    await open("H7 注意力");
    await waitFor(() => expect(screen.getByRole("option", { name: /identity-visual/ })).toBeInTheDocument());
    fireEvent.change(screen.getByRole("combobox", { name: "选择运行记录" }), { target: { value: "identity-visual" } });
    expect((await screen.findAllByText(/本次视觉参考任务未启用/))[0]).toBeVisible();
    await act(async () => { resolveJob(response(job("identity-current", faceid, "basic"))); });
    expect(screen.getByText(enableAdvice)).toBeVisible();
    expect(within(screen.getByRole("tabpanel", { name: "H7 注意力" })).queryByRole("img")).not.toBeInTheDocument();
  });
});
