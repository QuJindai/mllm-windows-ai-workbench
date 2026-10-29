import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RefinementWorkspace } from "./RefinementWorkspace";
import { IdentityResults } from "./IdentityResults";
import type { IdentityJob } from "../../../domain/identity";
import { announceImageDeleted } from "../../image-deletion";
import { DreamProviderContext } from "../../providers";
import { MockDreamProvider } from "../../../providers/MockDreamProvider";

const version = (id: string, state = "complete", extra: Record<string, unknown> = {}) => ({
  id, state, message: state, createdAt: "2026-10-29T00:00:00Z", parentVersionId: "result",
  settings: {}, ...(state === "complete" ? { imageUrl: `/images/${id}.png` } : {}), ...extra,
});
const snapshot = (extra: Record<string, unknown> = {}) => ({
  sourceJobId: "identity-source", selectedVersionId: "result",
  versions: [version("result"), version("original")], ...extra,
});
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
};
let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;
beforeEach(() => {
  fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => response(snapshot()));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const open = () => render(<RefinementWorkspace sourceJobId="identity-source" onClose={vi.fn()} />);
const ready = () => screen.findByRole("button", { name: "精修一轮" });
const postCalls = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");
const tick = async (ms = 1600) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

describe("RefinementWorkspace HTTP workflow", () => {
  it("loads server modes and submits exactly one round using the selected parent and exact payload", async () => {
    const gate = deferred<Response>();
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST" ? gate.promise : response(snapshot({
      selectedVersionId: "refine-existing", modes: ["redraw", "reference-anchor"], defaultMode: "reference-anchor",
      versions: [version("result"), version("original"), version("refine-existing")],
    })));
    open();
    await ready();
    expect(screen.getByLabelText("精修模式")).toHaveValue("reference-anchor");
    expect(screen.queryByRole("option", { name: "人脸修复" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("精修强度"), { target: { value: "0.45" } });
    fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "保留眼神" } });
    fireEvent.change(screen.getByLabelText("精修负面提示词"), { target: { value: "过度磨皮" } });
    fireEvent.change(screen.getByLabelText("精修种子"), { target: { value: "123" } });
    fireEvent.click(await ready()); fireEvent.click(await ready());
    expect(postCalls()).toHaveLength(1);
    expect(postCalls()[0][0]).toBe("/api/identity/refinements");
    expect(JSON.parse(postCalls()[0][1]!.body as string)).toEqual({ sourceJobId: "identity-source", parentVersionId: "refine-existing", mode: "reference-anchor", strength: 0.45, prompt: "保留眼神", negativePrompt: "过度磨皮", seed: 123, requestId: expect.stringMatching(/^[\da-f-]{36}$/i) });
    expect(await ready()).toBeDisabled();
    await act(async () => { gate.resolve(response(version("refine-new", "queued"))); });
  });

  it("uses restore only when capability metadata is absent", async () => {
    open(); await ready();
    expect(screen.getByLabelText("精修模式")).toHaveValue("restore");
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });

  it("hides unused diffusion inputs for deterministic restoration and explains the detail strength", async () => {
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST" ? response(version("refine-plain", "queued"))
      : response(snapshot({ usesDiffusion: false, modes: ["restore"], defaultMode: "restore" })));
    open(); await ready();
    expect(screen.getByText("身份修复不使用提示词和随机种子")).toBeInTheDocument();
    expect(screen.queryByLabelText("精修提示词")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("精修负面提示词")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("精修种子")).not.toBeInTheDocument();
    expect(screen.getByText(/仅调节.*GFPGAN.*身份回贴始终执行/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("细节修复强度"), { target: { value: "0.25" } });
    fireEvent.click(await ready());
    expect(JSON.parse(postCalls()[0][1]!.body as string)).toEqual({ sourceJobId: "identity-source", parentVersionId: "result", mode: "restore", strength: .25,
      prompt: "", negativePrompt: "", seed: 0, requestId: expect.any(String) });
  });

  it.each([true, undefined])("keeps diffusion controls for anime restore and legacy metadata (usesDiffusion=%s)", async (usesDiffusion) => {
    fetchMock.mockImplementation(async () => response(snapshot({ modes: ["restore"], usesDiffusion })));
    open(); await ready();
    expect(screen.getByLabelText("精修提示词")).toBeEnabled();
    expect(screen.getByLabelText("精修负面提示词")).toBeEnabled();
    expect(screen.getByLabelText("精修种子")).toBeEnabled();
    expect(screen.getByLabelText("精修强度")).toBeEnabled();
    expect(screen.queryByText("身份修复不使用提示词和随机种子")).not.toBeInTheDocument();
  });

  it.each([
    { route: "FaceID", modes: ["restore", "edge-lighting"], defaultMode: "restore", usesDiffusion: false },
    { route: "anime", modes: ["restore", "edge-lighting"], defaultMode: "restore", usesDiffusion: true },
    { route: "visual", modes: ["redraw", "reference-anchor", "edge-lighting"], defaultMode: "redraw", usesDiffusion: true },
    { route: "legacy", modes: ["redraw", "reference-anchor", "edge-lighting"], defaultMode: undefined, usesDiffusion: undefined },
  ])("offers edge-lighting without changing the $route default and submits without diffusion inputs", async ({ modes, defaultMode, usesDiffusion }) => {
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST" ? response(version("refine-lighting", "queued"))
      : response(snapshot({ modes, defaultMode, usesDiffusion, selectedVersionId: "refine-opaque-parent",
        versions: [version("result"), version("original"), version("refine-opaque-parent")],
      })));
    open(); await ready();
    expect(screen.getByLabelText("精修模式")).toHaveValue(defaultMode ?? "redraw");
    expect(screen.getByRole("option", { name: "边缘光照协调" })).toHaveValue("edge-lighting");
    if (usesDiffusion !== false) {
      fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "旧提示词" } });
      fireEvent.change(screen.getByLabelText("精修负面提示词"), { target: { value: "旧负面词" } });
      fireEvent.change(screen.getByLabelText("精修种子"), { target: { value: "" } });
      expect(await ready()).toBeDisabled();
    }
    fireEvent.change(screen.getByLabelText("精修模式"), { target: { value: "edge-lighting" } });
    expect(screen.queryByLabelText("精修提示词")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("精修负面提示词")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("精修种子")).not.toBeInTheDocument();
    expect(screen.queryByText(/GFPGAN/)).not.toBeInTheDocument();
    expect(screen.getByText("边缘光照协调不使用提示词和随机种子")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("协调强度"), { target: { value: "0.25" } });
    expect(await ready()).toBeEnabled();
    fireEvent.click(await ready());
    expect(postCalls()).toHaveLength(1);
    expect(JSON.parse(postCalls()[0][1]!.body as string)).toEqual({ sourceJobId: "identity-source", parentVersionId: "refine-opaque-parent",
      mode: "edge-lighting", strength: .25, prompt: "", negativePrompt: "", seed: 0, requestId: expect.stringMatching(/^[\da-f-]{36}$/i) });
    await waitFor(() => expect(screen.getByText("有精修版本正在处理，完成或取消后可继续。")).toBeInTheDocument());
    expect(screen.getByLabelText("精修模式")).toBeDisabled();
  });

  it("retains an edge-lighting retry UUID but starts a new submission after switching modes", async () => {
    let attempts = 0;
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST"
      ? ++attempts < 3 ? response({ detail: "暂不可用" }, 503) : response(version("refine-lighting", "queued"))
      : response(snapshot({ modes: ["redraw", "reference-anchor", "edge-lighting"], defaultMode: "redraw", usesDiffusion: true })));
    open(); await ready();
    fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "保留眼神" } });
    fireEvent.change(screen.getByLabelText("精修负面提示词"), { target: { value: "过度磨皮" } });
    fireEvent.change(screen.getByLabelText("精修种子"), { target: { value: "137" } });
    fireEvent.change(screen.getByLabelText("精修模式"), { target: { value: "edge-lighting" } });
    fireEvent.click(await ready());
    await waitFor(() => expect(screen.getByRole("button", { name: "重试本次提交" })).toBeEnabled());
    const first = JSON.parse(postCalls()[0][1]!.body as string);
    expect(first).toMatchObject({ mode: "edge-lighting", prompt: "", negativePrompt: "", seed: 0 });
    fireEvent.click(screen.getByRole("button", { name: "重试本次提交" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "重试本次提交" })).toBeEnabled());
    expect(JSON.parse(postCalls()[1][1]!.body as string)).toEqual(first);
    fireEvent.change(screen.getByLabelText("精修模式"), { target: { value: "redraw" } });
    expect(screen.queryByRole("button", { name: "重试本次提交" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("精修提示词")).toHaveValue("保留眼神");
    expect(screen.getByLabelText("精修负面提示词")).toHaveValue("过度磨皮");
    expect(screen.getByLabelText("精修种子")).toHaveValue(137);
    expect(screen.getByLabelText("精修强度")).toBeEnabled();
    fireEvent.change(screen.getByLabelText("精修模式"), { target: { value: "edge-lighting" } });
    fireEvent.click(await ready());
    const fresh = JSON.parse(postCalls()[2][1]!.body as string);
    expect(fresh).toMatchObject({ mode: "edge-lighting", prompt: "", negativePrompt: "", seed: 0 });
    expect(fresh.requestId).not.toBe(first.requestId);
    await waitFor(() => expect(screen.getByText("有精修版本正在处理，完成或取消后可继续。")).toBeInTheDocument());
  });

  it("does not let a now-hidden invalid seed block deterministic restoration after a capability refresh", async () => {
    vi.useFakeTimers();
    let usesDiffusion = true;
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST" ? response(version("refine-plain", "queued"))
      : response(snapshot({ usesDiffusion, modes: ["restore"] })));
    open(); await tick(0);
    fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "旧提示词" } });
    fireEvent.change(screen.getByLabelText("精修种子"), { target: { value: "" } });
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeDisabled();
    usesDiffusion = false; await tick(5000);
    expect(screen.queryByLabelText("精修种子")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "精修一轮" })); await tick(0);
    expect(JSON.parse(postCalls()[0][1]!.body as string)).toMatchObject({ prompt: "", negativePrompt: "", seed: 0 });
  });

  it("rejects malformed diffusion capability metadata instead of exposing ignored controls", async () => {
    fetchMock.mockImplementation(async () => response(snapshot({ usesDiffusion: "false" })));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("版本列表无效");
    expect(screen.queryByLabelText("精修提示词")).not.toBeInTheDocument();
  });

  it("shows measured phases and protected/outside pixel counts against the named baseline, never a likeness score", async () => {
    fetchMock.mockImplementation(async () => response(snapshot({ versions: [version("result"), version("original"), version("refine-measured", "complete", {
      metrics: { durationMs: 3552.5, phasesMs: { read: 0, load: 1250, polish: 2300, diagnostics: .5, save: 2 }, similarity: .999,
        diagnostics: { schemaVersion: 1, baselineLabel: "selected-source", candidateLabel: "refinement", retention: {
          whole: { pixelCount: 1000, changedPixels: 40 }, protected: { pixelCount: 100, changedPixels: 0 }, outsideEdit: { pixelCount: 800, changedPixels: 2 },
        } } },
    })] })));
    open(); await ready();
    fireEvent.click(screen.getByText("精修 1 · 实测记录"));
    const phases = within(screen.getByRole("table", { name: "精修 1 阶段耗时" }));
    expect(phases.getByRole("row", { name: "读取父图 0 毫秒" })).toBeInTheDocument();
    expect(phases.getByRole("row", { name: "加载模型 1.3 秒" })).toBeInTheDocument();
    expect(phases.getByRole("row", { name: "执行精修 2.3 秒" })).toBeInTheDocument();
    expect(screen.getByText("总耗时：3.6 秒")).toBeInTheDocument();
    const pixels = within(screen.getByRole("table", { name: "精修 1 区域像素变化" }));
    expect(pixels.getByRole("row", { name: "全图 1000 40" })).toBeInTheDocument();
    expect(pixels.getByRole("row", { name: "保护区 100 0" })).toBeInTheDocument();
    expect(pixels.getByRole("row", { name: "编辑掩膜外 800 2" })).toBeInTheDocument();
    expect(screen.getByText(/selected-source.*refinement/)).toBeInTheDocument();
    expect(screen.getByText(/像素变化.*不代表人物相似度或画质评分/)).toBeInTheDocument();
    expect(screen.queryByText(/99.9/)).not.toBeInTheDocument();
  });

  it("shows long restore timings in seconds while retaining sub-second measurements", async () => {
    fetchMock.mockImplementation(async () => response(snapshot({ usesDiffusion: false, modes: ["restore", "edge-lighting"], defaultMode: "restore",
      versions: [version("result"), version("original"), version("refine-timed", "complete", {
        metrics: { durationMs: 75000, phasesMs: { read: .5, load: 51300.2, polish: 14100.4, diagnostics: 1000, save: 999.9 } },
      })],
    })));
    open(); await ready(); fireEvent.click(screen.getByText("精修 1 · 实测记录"));
    expect(screen.getByText("总耗时：75 秒")).toBeInTheDocument();
    const phases = within(screen.getByRole("table", { name: "精修 1 阶段耗时" }));
    expect(phases.getByRole("row", { name: "加载模型 51.3 秒" })).toBeInTheDocument();
    expect(phases.getByRole("row", { name: "执行精修 14.1 秒" })).toBeInTheDocument();
    expect(phases.getByRole("row", { name: "读取父图 0.5 毫秒" })).toBeInTheDocument();
    expect(phases.getByRole("row", { name: "像素诊断 1 秒" })).toBeInTheDocument();
    expect(phases.getByRole("row", { name: "保存图像 999.9 毫秒" })).toBeInTheDocument();
    expect(screen.queryByLabelText("精修种子")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("精修提示词")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("精修负面提示词")).not.toBeInTheDocument();
  });

  it("does not turn missing or invalid region measurements into zero changes", async () => {
    fetchMock.mockImplementation(async () => response(snapshot({ versions: [version("result"), version("original"), version("refine-partial", "complete", {
      metrics: { phasesMs: { read: 0, load: -1, polish: "10", save: null }, diagnostics: { schemaVersion: 1, retention: {
        whole: { pixelCount: 10, changedPixels: 2 }, protected: null, outsideEdit: { pixelCount: 8, changedPixels: 99 },
      } } },
    })] })));
    open(); await ready(); fireEvent.click(screen.getByText("精修 1 · 实测记录"));
    const phases = within(screen.getByRole("table", { name: "精修 1 阶段耗时" }));
    expect(phases.getAllByRole("row")).toHaveLength(2);
    const pixels = within(screen.getByRole("table", { name: "精修 1 区域像素变化" }));
    expect(pixels.getByRole("row", { name: "保护区 未返回 未返回" })).toBeInTheDocument();
    expect(pixels.getByRole("row", { name: "编辑掩膜外 未返回 未返回" })).toBeInTheDocument();
    expect(screen.queryByText(/99/)).not.toBeInTheDocument();
  });

  it("does not invent supported modes when the server provides an empty or unknown list", async () => {
    fetchMock.mockResolvedValue(response(snapshot({ modes: ["future-mode"], defaultMode: "redraw" })));
    open(); expect(await ready()).toBeDisabled();
    expect(screen.getByText(/没有可用的精修模式/)).toBeInTheDocument();
  });

  it("validates strength and integer seed before crossing the HTTP boundary", async () => {
    open(); await ready();
    fireEvent.change(screen.getByLabelText("精修强度"), { target: { value: "0.9" } });
    expect(await ready()).toBeDisabled();
    fireEvent.change(screen.getByLabelText("精修强度"), { target: { value: "0.25" } });
    for (const value of ["1.5", "-1", "2147483648", ""]) {
      fireEvent.change(screen.getByLabelText("精修种子"), { target: { value } });
      expect(await ready()).toBeDisabled();
    }
    fireEvent.change(screen.getByLabelText("精修种子"), { target: { value: "2147483647" } });
    expect(await ready()).toBeEnabled(); expect(postCalls()).toHaveLength(0);
  });

  it("selects a completed version and reverts through the select endpoint without modifying history", async () => {
    const versions = [version("result"), version("original"), version("refine-first")];
    fetchMock.mockImplementation(async (_url, init) => response(snapshot({ versions,
      selectedVersionId: init?.method === "POST" ? JSON.parse(init.body as string).versionId : "result",
    })));
    open(); await ready();
    for (const [name, id] of [["选择精修 1", "refine-first"], ["回到生成原图", "original"], ["回到生成结果", "result"]]) {
      fireEvent.click(screen.getByRole("button", { name }));
      await waitFor(() => expect(screen.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true"));
      expect(postCalls().at(-1)?.[0]).toBe("/api/identity/jobs/identity-source/refinements/select");
      expect(JSON.parse(postCalls().at(-1)![1]!.body as string)).toEqual({ versionId: id });
      expect(screen.getByRole("img", { name: "当前精修图像" })).toHaveAttribute("src", `/images/${id}.png`);
    }
  });

  it("polls without overlap, disables editing while active and stops after unmount", async () => {
    vi.useFakeTimers();
    const gate = deferred<Response>();
    fetchMock.mockResolvedValueOnce(response(snapshot({ versions: [version("result"), version("original"), version("refine-running", "running")] })))
      .mockImplementationOnce(() => gate.promise);
    const view = open(); await tick(0);
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeDisabled();
    expect(screen.getByLabelText("精修提示词")).toBeDisabled();
    await tick(); await tick(5000); expect(fetchMock).toHaveBeenCalledTimes(2);
    await act(async () => { gate.resolve(response(snapshot({ versions: [version("result"), version("original"), version("refine-running")] }))); });
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeEnabled();
    view.unmount(); await tick(10000); expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("cancels the active version and ignores a stale in-flight poll", async () => {
    vi.useFakeTimers();
    const active = snapshot({ versions: [version("result"), version("original"), version("refine-running", "running")] });
    const gate = deferred<Response>();
    fetchMock.mockResolvedValueOnce(response(active)).mockImplementationOnce(() => gate.promise)
      .mockResolvedValueOnce(response(version("refine-running", "cancelled")));
    open(); await tick(0); await tick();
    fireEvent.click(screen.getByRole("button", { name: "取消精修 1" })); await tick(0);
    expect(postCalls()[0][0]).toBe("/api/identity/refinements/refine-running/cancel");
    await act(async () => { gate.resolve(response(active)); });
    expect(screen.getByText("已取消")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeEnabled();
    expect(screen.getByRole("img", { name: "当前精修图像" })).toHaveAttribute("src", "/images/result.png");
  });

  it("preserves versions and form input on a polling error and recovers on a later poll", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValueOnce(response(snapshot({ versions: [version("result"), version("original"), version("refine-running", "running")] })))
      .mockRejectedValueOnce(new Error("连接中断")).mockResolvedValue(response(snapshot()));
    open(); await tick(0); await tick();
    expect(screen.getByRole("alert")).toHaveTextContent("连接中断");
    expect(screen.getByRole("img", { name: "当前精修图像" })).toHaveAttribute("src", "/images/result.png");
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeDisabled();
    await tick(6000); expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeEnabled();
  });

  it("reconciles an uncertain creation without resubmitting it and preserves the prompt", async () => {
    const gate = deferred<Response>();
    fetchMock.mockResolvedValueOnce(response(snapshot())).mockRejectedValueOnce(new Error("响应丢失"))
      .mockImplementationOnce(() => gate.promise);
    open(); await ready();
    fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "保留细节" } });
    fireEvent.click(await ready());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(await ready()).toBeDisabled();
    await act(async () => { gate.resolve(response(snapshot({ versions: [version("result"), version("original"), version("refine-accepted", "running")] }))); });
    expect(postCalls()).toHaveLength(1);
    expect(screen.getByLabelText("精修提示词")).toHaveValue("保留细节");
    expect(screen.getByRole("alert")).toHaveTextContent("响应丢失");
  });

  it("keeps failed versions visible without making them selectable or claiming quality metrics", async () => {
    fetchMock.mockResolvedValue(response(snapshot({ versions: [version("result"), version("original"), version("refine-failed", "failed", { error: "未找到人脸", metrics: { similarity: 0.99 } })] })));
    open(); await ready();
    expect(screen.getByText("未找到人脸")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择精修 1" })).toBeDisabled();
    expect(screen.queryByText(/99|相似度/)).not.toBeInTheDocument();
  });

  it("reuses the request UUID on explicit retry but allocates a new one after settings change", async () => {
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST"
      ? response({ detail: "服务暂不可用" }, 503) : response(snapshot()));
    open(); await ready();
    fireEvent.click(await ready());
    const retry = await screen.findByRole("button", { name: "重试本次提交" });
    await waitFor(() => expect(retry).toBeEnabled());
    const first = JSON.parse(postCalls()[0][1]!.body as string);
    // Implicit form submission must not bypass the disabled new-submission button.
    fireEvent.submit(screen.getByLabelText("精修提示词").closest("form")!);
    expect(postCalls()).toHaveLength(1);
    fireEvent.click(retry);
    await waitFor(() => expect(postCalls()).toHaveLength(2));
    expect(JSON.parse(postCalls()[1][1]!.body as string)).toEqual(first);
    await waitFor(() => expect(screen.getByLabelText("精修提示词")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "新参数" } });
    expect(screen.queryByRole("button", { name: "重试本次提交" })).not.toBeInTheDocument();
    fireEvent.click(await ready());
    await waitFor(() => expect(postCalls()).toHaveLength(3));
    const next = JSON.parse(postCalls()[2][1]!.body as string);
    expect(next.requestId).not.toBe(first.requestId);
    expect(next.prompt).toBe("新参数");
  });

  it("keeps version labels stable when an older version is returned by an idempotent retry", async () => {
    const versions = [version("result"), version("original"), version("refine-older"), version("refine-newer")];
    fetchMock.mockImplementation(async (_url, init) => init?.method === "POST"
      ? response(version("refine-older")) : response(snapshot({ versions })));
    open(); await ready();
    fireEvent.click(await ready());
    await waitFor(() => expect(screen.getByRole("button", { name: "选择精修 1" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "选择精修 1" }));
    await waitFor(() => expect(postCalls()).toHaveLength(2));
    expect(JSON.parse(postCalls()[1][1]!.body as string)).toEqual({ versionId: "refine-older" });
  });

  it.each([false, true])("retains retry identity until a different parent is confirmed (selection fails=%s)", async (fails) => {
    fetchMock.mockImplementation(async (url, init) => {
      if (String(url).endsWith("/select")) return fails ? response({ detail: "选择失败" }, 503) : response(snapshot());
      if (init?.method === "POST") return response({ detail: "提交响应丢失" }, 503);
      return response(snapshot({ versions: [version("result"), version("original")] }));
    });
    open(); await ready(); fireEvent.click(await ready());
    await waitFor(() => expect(screen.getByRole("button", { name: "重试本次提交" })).toBeEnabled());
    const first = JSON.parse(postCalls()[0][1]!.body as string);
    fireEvent.click(screen.getByRole("button", { name: fails ? "回到生成原图" : "回到生成结果" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "重试本次提交" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "重试本次提交" }));
    await waitFor(() => expect(postCalls().filter(([url]) => url === "/api/identity/refinements")).toHaveLength(2));
    expect(JSON.parse(postCalls().at(-1)![1]!.body as string)).toEqual(first);
  });

  it("retries a transient image failure without changing the selected parent or edit settings", async () => {
    open(); await ready();
    fireEvent.change(screen.getByLabelText("精修提示词"), { target: { value: "保留细节" } });
    fireEvent.error(screen.getByRole("img", { name: "当前精修图像" }));
    expect(await ready()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "重试当前图像" }));
    expect(screen.getByRole("img", { name: "当前精修图像" })).toHaveAttribute("src", "/images/result.png");
    expect(screen.getByLabelText("精修提示词")).toHaveValue("保留细节");
    expect(postCalls()).toHaveLength(0);
  });

  it("blocks unusable images and clears all previews when the source is gone", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValueOnce(response(snapshot())).mockResolvedValue(response({ detail: "父图已删除" }, 404));
    open(); await tick(0);
    fireEvent.error(screen.getByRole("img", { name: "当前精修图像" }));
    expect(screen.getByText(/当前版本图片不可用/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "精修一轮" })).toBeDisabled();
    await tick(6000);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("父图已删除");
    const count = fetchMock.mock.calls.length; await tick(10000); expect(fetchMock).toHaveBeenCalledTimes(count);
  });

  it("does not let a late old-source response overwrite a new workspace", async () => {
    const gate = deferred<Response>();
    fetchMock.mockImplementation(async (url) => String(url).includes("identity-source/") ? gate.promise : response(snapshot({ sourceJobId: "identity-other", selectedVersionId: "original" })));
    const view = open();
    view.rerender(<RefinementWorkspace sourceJobId="identity-other" onClose={vi.fn()} />);
    await ready();
    await act(async () => { gate.resolve(response(snapshot())); });
    expect(screen.getByRole("button", { name: "回到生成原图" })).toHaveAttribute("aria-pressed", "true");
  });

  it("survives StrictMode effect replay and offers retry after initial HTTP validation errors", async () => {
    fetchMock.mockImplementation(async () => response({ detail: [{ msg: "参数错误" }] }, 422));
    render(<StrictMode><RefinementWorkspace sourceJobId="identity-source" onClose={vi.fn()} /></StrictMode>);
    expect(await screen.findByRole("alert")).toHaveTextContent("参数错误");
    fetchMock.mockImplementation(async () => response(snapshot()));
    fireEvent.click(screen.getByRole("button", { name: "重试读取版本" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "精修一轮" })).toBeEnabled());
  });
});

it("opens refinement from identity results and unmounts it after confirmed source deletion", async () => {
  const provider = new MockDreamProvider();
  const job: IdentityJob = { id: "identity-source", state: "complete", progress: 100, message: "完成", error: null,
    request: { referenceId: "ref", faceIndex: 0, prompt: "portrait", negativePrompt: "", seed: 42, width: 512, height: 768, steps: 28, cfg: 5.5, identityStrength: 0.8, structureStrength: 1, faceLoraStrength: 0.6, facePolish: false, faceRestoreStrength: 0.4 },
    result: { imageUrl: "/images/result.png", metadata: {} } };
  render(<DreamProviderContext.Provider value={provider}><IdentityResults batch={null} job={job} profile={null} opening={false} cancelling={false} pending={false} pollError={null} onCancel={vi.fn()} onSavePreset={vi.fn()} /></DreamProviderContext.Provider>);
  fireEvent.click(screen.getByRole("button", { name: "独立精修" })); await ready();
  act(() => announceImageDeleted("identity-source", provider));
  expect(screen.queryByRole("button", { name: "精修一轮" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "独立精修" })).not.toBeInTheDocument();
  expect(screen.getByText(/仍可复用生成参数/)).toBeInTheDocument();
});
