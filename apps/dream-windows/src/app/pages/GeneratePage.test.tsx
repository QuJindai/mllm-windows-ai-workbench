import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GeneratePage } from "./GeneratePage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import hardwareFixture from "../../fixtures/hardware.json";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { GenerationJob, GenerationRequest } from "../../domain/generation";

describe("Generate page", () => {
  it("submits a typed request and renders the mock result lifecycle", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    const submit = await screen.findByRole("button", { name: "生成图像" });
    await waitFor(() => expect(submit).toBeEnabled());
    expect(screen.getByRole("combobox", { name: "显微镜采集" })).toHaveValue("basic");
    fireEvent.click(submit);
    expect(await screen.findByRole("progressbar", { name: "生成进度" })).toBeVisible();
    await waitFor(() => expect(screen.getAllByText("完成").length).toBeGreaterThan(0), { timeout: 1800 });
    expect(screen.getByAltText("模拟生成结果")).toBeVisible();
    expect(screen.queryByAltText("批量结果 1")).not.toBeInTheDocument();
  });

  it("switches the result workbench between preview, real metadata, and variants", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("button", { name: "生成图像" }));
    await waitFor(() => expect(screen.getAllByText("完成").length).toBeGreaterThan(0), { timeout: 1800 });

    fireEvent.click(screen.getByRole("tab", { name: "元数据" }));
    expect(screen.getByRole("tabpanel", { name: "元数据" })).toHaveTextContent("768 × 768");
    expect(screen.getByRole("tabpanel", { name: "元数据" })).toHaveTextContent("mock");
    expect(screen.queryByAltText("模拟生成结果")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "变体（1）" }));
    expect(screen.getByRole("tabpanel", { name: "变体（1）" })).toBeVisible();
    expect(screen.getByAltText("批量结果 1")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "预览" }));
    expect(screen.getByRole("tabpanel", { name: "预览" })).toBeVisible();
    expect(screen.getByAltText("模拟生成结果")).toBeVisible();
    expect(screen.queryByAltText("批量结果 1")).not.toBeInTheDocument();
  });

  it("renders nested backend metadata as readable JSON", async () => {
    class NestedMetadataProvider extends MockDreamProvider {
      override async getJob(id: string): Promise<GenerationJob> {
        const job = await super.getJob(id);
        return job.result ? { ...job, result: { ...job.result, metadata: { ...job.result.metadata, dmd2: { mode: "standard", weight: 1 } } } } : job;
      }
    }
    render(<DreamProviderContext.Provider value={new NestedMetadataProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("button", { name: "生成图像" }));
    await waitFor(() => expect(screen.getAllByText("完成").length).toBeGreaterThan(0), { timeout: 1800 });
    fireEvent.click(screen.getByRole("tab", { name: "元数据" }));

    expect(screen.getByRole("tabpanel", { name: "元数据" })).toHaveTextContent('{"mode":"standard","weight":1}');
    expect(screen.getByRole("tabpanel", { name: "元数据" })).not.toHaveTextContent("[object Object]");
  });

  it("starts with the balanced standard-model profile", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);

    await screen.findByRole("button", { name: "生成图像" });
    expect(screen.getByRole("combobox", { name: "模型" })).toHaveValue("cyberrealistic-xl-v10-standard");
    expect(screen.getByLabelText("Width")).toHaveValue(768);
    expect(screen.getByLabelText("Height")).toHaveValue(768);
    expect(screen.getByLabelText("Steps")).toHaveValue(20);
    expect(screen.getByLabelText("CFG")).toHaveValue(4);
    expect(screen.getByRole("combobox", { name: "采样器" })).toHaveValue("dpm++2m_sde");
    expect(screen.getByRole("combobox", { name: "调度器" })).toHaveValue("karras");
    expect(screen.getByRole("combobox", { name: "显微镜采集" })).toHaveValue("basic");
  });

  it("disables submission when the prompt is empty", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    const prompt = await screen.findByLabelText("正向提示词");
    fireEvent.change(prompt, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "生成图像" })).toBeDisabled();
  });

  it("blocks low-quality parameters and explains why", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    await screen.findByRole("button", { name: "生成图像" });
    fireEvent.change(screen.getByLabelText("Width"), { target: { value: "256" } });
    fireEvent.change(screen.getByLabelText("Height"), { target: { value: "256" } });
    fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "2" } });

    expect(screen.getByRole("alert")).toHaveTextContent("质量保护");
    expect(screen.getByRole("button", { name: "生成图像" })).toBeDisabled();
  });

  it("disables generation and explains when CUDA is unavailable", async () => {
    const hardware: HardwareSnapshot = { ...(hardwareFixture as HardwareSnapshot), cudaReady: false, truth: "unavailable" };
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage hardware={hardware} /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("button", { name: "生成图像" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("CUDA 不可用");
  });

  it("renders a provider error when a generation job fails", async () => {
    class FailingProvider extends MockDreamProvider {
      override async getJob(id: string): Promise<GenerationJob> {
        const job = await super.getJob(id);
        return { ...job, state: "failed", progress: 0, message: "Generation failed", error: "CUDA kernel unavailable" };
      }
    }

    render(<DreamProviderContext.Provider value={new FailingProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("button", { name: "生成图像" }));

    expect(await screen.findByText("CUDA kernel unavailable")).toBeVisible();
  });

  it("submits immediately and polls status at a 750 ms cadence", async () => {
    vi.useFakeTimers();
    class PollTrackingProvider extends MockDreamProvider {
      readonly generatedRequests: GenerationRequest[] = [];
      readonly pollTimes: number[] = [];

      override async generate(request: GenerationRequest) {
        this.generatedRequests.push(request);
        return super.generate(request);
      }

      override async getJob(id: string): Promise<GenerationJob> {
        this.pollTimes.push(Date.now());
        const job = await super.getJob(id);
        if (this.pollTimes.length === 1) {
          return { ...job, state: "sampling", progress: 50, message: "采样中", result: undefined };
        }
        return { ...job, state: "complete", progress: 100, message: "模拟生成完成" };
      }
    }

    try {
      const provider = new PollTrackingProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });

      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests).toHaveLength(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(749); });
      expect(provider.pollTimes).toHaveLength(0);

      await act(async () => { await vi.advanceTimersByTimeAsync(1); });
      expect(provider.pollTimes).toHaveLength(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(749); });
      expect(provider.pollTimes).toHaveLength(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(1); });
      expect(provider.pollTimes).toHaveLength(2);
      expect(screen.getByAltText("模拟生成结果")).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not poll after cancellation during the polling wait", async () => {
    vi.useFakeTimers();
    class WaitCancellationProvider extends MockDreamProvider {
      readonly cancelledIds: string[] = [];
      readonly polledIds: string[] = [];

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return super.cancelJob(id);
      }

      override async getJob(id: string): Promise<GenerationJob> {
        this.polledIds.push(id);
        return super.getJob(id);
      }
    }

    try {
      const provider = new WaitCancellationProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });

      await act(async () => { await vi.advanceTimersByTimeAsync(300); });
      fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.cancelledIds).toEqual(["mock-job-1"]);

      await act(async () => { await vi.advanceTimersByTimeAsync(450); });
      expect(provider.polledIds).toHaveLength(0);
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each(["resolve", "reject"] as const)("ignores an in-flight poll that %s after cancellation", async (outcome) => {
    vi.useFakeTimers();
    let resolvePoll!: (job: GenerationJob) => void;
    let rejectPoll!: (reason: Error) => void;
    const pendingPoll = new Promise<GenerationJob>((resolve, reject) => {
      resolvePoll = resolve;
      rejectPoll = reject;
    });

    class InFlightPollProvider extends MockDreamProvider {
      readonly generatedRequests: GenerationRequest[] = [];
      readonly cancelledIds: string[] = [];
      readonly polledIds: string[] = [];

      override async generate(request: GenerationRequest) {
        this.generatedRequests.push(request);
        return { id: `in-flight-job-${this.generatedRequests.length}` };
      }

      override async getJob(id: string): Promise<GenerationJob> {
        this.polledIds.push(id);
        return pendingPoll;
      }

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return { id, request: this.generatedRequests[0], state: "cancelled", progress: 0, message: "已取消生成" };
      }
    }

    try {
      const provider = new InFlightPollProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText("批量数量"), { target: { value: "2" } });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });

      await act(async () => { await vi.advanceTimersByTimeAsync(750); });
      expect(provider.polledIds).toEqual(["in-flight-job-1"]);

      fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.cancelledIds).toEqual(["in-flight-job-1"]);
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);

      await act(async () => {
        if (outcome === "resolve") {
          resolvePoll({
            id: "in-flight-job-1",
            request: provider.generatedRequests[0],
            state: "complete",
            progress: 100,
            message: "stale completed result",
            result: { id: "stale-result", imageUrl: "data:image/png;base64,c3RhbGU=", truth: "demo", metadata: {} },
          });
        } else {
          rejectPoll(new Error("stale poll failed"));
        }
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(provider.generatedRequests).toHaveLength(1);
      expect(screen.queryAllByText("stale completed result")).toHaveLength(0);
      expect(screen.queryByRole("img", { name: /批量结果/ })).not.toBeInTheDocument();
      expect(screen.queryByText("stale poll failed")).not.toBeInTheDocument();
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it.each(["resolve", "reject"] as const)("releases a cancelled run without waiting for an in-flight poll that later %s", async (outcome) => {
    vi.useFakeTimers();
    let resolvePoll!: (job: GenerationJob) => void;
    let rejectPoll!: (reason: Error) => void;
    const pendingPoll = new Promise<GenerationJob>((resolve, reject) => {
      resolvePoll = resolve;
      rejectPoll = reject;
    });

    class NonSettlingPollProvider extends MockDreamProvider {
      readonly generatedRequests: GenerationRequest[] = [];
      readonly cancelledIds: string[] = [];
      readonly polledIds: string[] = [];

      override async generate(request: GenerationRequest) {
        this.generatedRequests.push(request);
        return { id: `non-settling-job-${this.generatedRequests.length}` };
      }

      override async getJob(id: string): Promise<GenerationJob> {
        this.polledIds.push(id);
        return pendingPoll;
      }

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return { id, request: this.generatedRequests[0], state: "cancelled", progress: 0, message: "已取消生成" };
      }
    }

    try {
      const provider = new NonSettlingPollProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText("批量数量"), { target: { value: "2" } });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });

      await act(async () => { await vi.advanceTimersByTimeAsync(750); });
      expect(provider.polledIds).toEqual(["non-settling-job-1"]);

      fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(provider.cancelledIds).toEqual(["non-settling-job-1"]);
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);
      const replacementSubmit = screen.getByRole("button", { name: "生成图像" });
      expect(replacementSubmit).toBeEnabled();

      fireEvent.click(replacementSubmit);
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests.map((generated) => generated.seed)).toEqual([20260906, 20260906]);

      await act(async () => {
        if (outcome === "resolve") {
          resolvePoll({
            id: "non-settling-job-1",
            request: provider.generatedRequests[0],
            state: "complete",
            progress: 100,
            message: "stale completed result",
            result: { id: "stale-result", imageUrl: "data:image/png;base64,c3RhbGU=", truth: "demo", metadata: {} },
          });
        } else {
          rejectPoll(new Error("stale poll failed"));
        }
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(provider.generatedRequests.map((generated) => generated.seed)).toEqual([20260906, 20260906]);
      expect(provider.polledIds).toEqual(["non-settling-job-1"]);
      expect(screen.getByRole("button", { name: "生成中…" })).toBeDisabled();
      expect(screen.queryAllByText("stale completed result")).toHaveLength(0);
      expect(screen.queryByRole("img", { name: /批量结果/ })).not.toBeInTheDocument();
      expect(screen.queryByText("stale poll failed")).not.toBeInTheDocument();
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("saves and selects a human-readable generation preset", async () => {
    window.localStorage.clear();
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    await screen.findByRole("button", { name: "生成图像" });

    fireEvent.change(screen.getByLabelText("Width"), { target: { value: "960" } });
    fireEvent.change(screen.getByLabelText("Height"), { target: { value: "1152" } });
    fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "28" } });
    fireEvent.click(screen.getByRole("tab", { name: "预设" }));
    fireEvent.change(screen.getByLabelText("预设名称"), { target: { value: "电影风景" } });
    fireEvent.click(screen.getByRole("button", { name: "保存预设" }));

    expect(window.localStorage).toHaveLength(1);
    const storageKey = window.localStorage.key(0);
    const savedPresets = JSON.parse(window.localStorage.getItem(storageKey ?? "") ?? "[]") as Array<{ name: string; request: GenerationRequest }>;
    expect(savedPresets).toMatchObject([{ name: "电影风景", request: { width: 960, height: 1152, steps: 28 } }]);

    fireEvent.change(screen.getByLabelText("Width"), { target: { value: "512" } });
    fireEvent.change(screen.getByLabelText("Height"), { target: { value: "512" } });
    fireEvent.change(screen.getByLabelText("Steps"), { target: { value: "8" } });
    expect(await screen.findByRole("button", { name: "选择预设 电影风景" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "选择预设 电影风景" }));
    expect(screen.getByRole("tab", { name: "提示词" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Width")).toHaveValue(960);
    expect(screen.getByLabelText("Height")).toHaveValue(1152);
    expect(screen.getByLabelText("Steps")).toHaveValue(28);
  });

  it("runs a batch serially and exposes each completed result", async () => {
    vi.useFakeTimers();
    class SerialProvider extends MockDreamProvider {
      readonly events: string[] = [];
      private readonly pollCounts = new Map<string, number>();

      override async generate(request: GenerationRequest) {
        const handle = await super.generate(request);
        this.events.push(`generate:${handle.id}`);
        return handle;
      }

      override async getJob(id: string): Promise<GenerationJob> {
        this.events.push(`getJob:${id}`);
        const polls = (this.pollCounts.get(id) ?? 0) + 1;
        this.pollCounts.set(id, polls);
        const job = await super.getJob(id);
        if (id === "mock-job-1" && polls === 1) {
          return { ...job, state: "sampling", progress: 50, message: "采样中", result: undefined };
        }
        return job;
      }
    }

    try {
      const provider = new SerialProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText("批量数量"), { target: { value: "2" } });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });

      expect(screen.getByText("批量队列 · 2 项")).toBeVisible();
      expect(provider.events).toEqual(["generate:mock-job-1"]);

      await act(async () => { await vi.advanceTimersByTimeAsync(750); });
      expect(provider.events).toEqual(["generate:mock-job-1", "getJob:mock-job-1"]);

      await act(async () => { await vi.advanceTimersByTimeAsync(749); });
      expect(provider.events).toEqual(["generate:mock-job-1", "getJob:mock-job-1"]);

      await act(async () => { await vi.advanceTimersByTimeAsync(1); });
      expect(provider.events).toEqual(["generate:mock-job-1", "getJob:mock-job-1", "getJob:mock-job-1", "generate:mock-job-2"]);

      await act(async () => { await vi.advanceTimersByTimeAsync(750); });
      expect(provider.events.at(-1)).toBe("getJob:mock-job-2");
      fireEvent.click(screen.getByRole("tab", { name: "变体（2）" }));
      expect(screen.getAllByRole("img", { name: /批量结果/ })).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops the remaining batch when polling the active job fails", async () => {
    vi.useFakeTimers();
    class PollFailureProvider extends MockDreamProvider {
      readonly generatedRequests: GenerationRequest[] = [];

      override async generate(request: GenerationRequest) {
        this.generatedRequests.push(request);
        return super.generate(request);
      }

      override async getJob(): Promise<GenerationJob> {
        throw new Error("polling connection lost");
      }
    }

    try {
      const provider = new PollFailureProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText("批量数量"), { target: { value: "2" } });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests).toHaveLength(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(750); });

      expect(screen.getByRole("alert")).toHaveTextContent("polling connection lost");
      expect(provider.generatedRequests).toHaveLength(1);
      expect(screen.getAllByText("队列已停止").length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels a handle that resolves after cancellation was requested", async () => {
    vi.useFakeTimers();
    let resolveHandle!: (handle: { id: string }) => void;
    const pendingHandle = new Promise<{ id: string }>((resolve) => { resolveHandle = resolve; });

    class DelayedHandleProvider extends MockDreamProvider {
      readonly generatedRequests: GenerationRequest[] = [];
      readonly cancelledIds: string[] = [];
      readonly polledIds: string[] = [];

      override async generate(request: GenerationRequest) {
        this.generatedRequests.push(request);
        return pendingHandle;
      }

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return { id, request: this.generatedRequests[0], state: "cancelled", progress: 0, message: "已取消生成" };
      }

      override async getJob(id: string): Promise<GenerationJob> {
        this.polledIds.push(id);
        return { id, request: this.generatedRequests[0], state: "sampling", progress: 30, message: "采样中" };
      }
    }

    try {
      const provider = new DelayedHandleProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText("批量数量"), { target: { value: "2" } });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests).toHaveLength(1);

      fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.cancelledIds).toHaveLength(0);

      await act(async () => {
        resolveHandle({ id: "delayed-job-1" });
        await Promise.resolve();
      });

      expect(provider.cancelledIds).toEqual(["delayed-job-1"]);
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);
      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(provider.generatedRequests).toHaveLength(1);
      expect(provider.polledIds).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("blocks replacement submission until delayed-handle cancellation settles", async () => {
    vi.useFakeTimers();
    let resolveHandle!: (handle: { id: string }) => void;
    let resolveCancellation!: (job: GenerationJob) => void;
    const pendingHandle = new Promise<{ id: string }>((resolve) => { resolveHandle = resolve; });
    const pendingCancellation = new Promise<GenerationJob>((resolve) => { resolveCancellation = resolve; });

    class DelayedCancellationProvider extends MockDreamProvider {
      readonly generatedRequests: GenerationRequest[] = [];
      readonly cancelledIds: string[] = [];

      override async generate(request: GenerationRequest) {
        this.generatedRequests.push(request);
        if (this.generatedRequests.length === 1) return pendingHandle;
        return { id: `replacement-job-${this.generatedRequests.length}` };
      }

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return pendingCancellation;
      }
    }

    try {
      const provider = new DelayedCancellationProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      const form = screen.getByRole("button", { name: "生成图像" }).closest("form");
      expect(form).not.toBeNull();

      fireEvent.submit(form as HTMLFormElement);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
      fireEvent.submit(form as HTMLFormElement);
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests).toHaveLength(1);

      await act(async () => {
        resolveHandle({ id: "delayed-job-1" });
        await Promise.resolve();
      });
      expect(provider.cancelledIds).toEqual(["delayed-job-1"]);

      fireEvent.submit(form as HTMLFormElement);
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests).toHaveLength(1);

      await act(async () => {
        resolveCancellation({ id: "delayed-job-1", request: provider.generatedRequests[0], state: "cancelled", progress: 0, message: "已取消生成" });
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);

      fireEvent.submit(form as HTMLFormElement);
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedRequests).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels the active native job without starting the next batch item", async () => {
    vi.useFakeTimers();
    class SlowProvider extends MockDreamProvider {
      readonly generatedIds: string[] = [];
      readonly cancelledIds: string[] = [];

      override async generate(request: GenerationRequest) {
        const handle = await super.generate(request);
        this.generatedIds.push(handle.id);
        return handle;
      }

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return super.cancelJob(id);
      }

      override async getJob(id: string): Promise<GenerationJob> {
        const job = await super.getJob(id);
        return { ...job, state: "sampling", progress: 30, message: "采样步骤 6 / 20", result: undefined };
      }
    }

    try {
      const provider = new SlowProvider();
      render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      fireEvent.change(screen.getByLabelText("批量数量"), { target: { value: "2" } });
      fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.generatedIds).toEqual(["mock-job-1"]);

      fireEvent.click(screen.getByRole("button", { name: "取消生成" }));
      await act(async () => { await Promise.resolve(); });
      expect(provider.cancelledIds).toEqual(["mock-job-1"]);

      await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
      expect(provider.generatedIds).toEqual(["mock-job-1"]);
      expect(screen.getAllByText("已取消生成").length).toBeGreaterThan(0);
      expect(screen.getAllByText("队列已停止").length).toBeGreaterThan(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels an active native job when the Generate page unmounts", async () => {
    class UnmountProvider extends MockDreamProvider {
      readonly cancelledIds: string[] = [];

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return super.cancelJob(id);
      }

      override async getJob(id: string): Promise<GenerationJob> {
        const job = await super.getJob(id);
        return { ...job, state: "sampling", progress: 30, message: "采样中", result: undefined };
      }
    }

    const provider = new UnmountProvider();
    const view = render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
    await act(async () => { await Promise.resolve(); });

    view.unmount();
    await act(async () => { await Promise.resolve(); });

    expect(provider.cancelledIds).toEqual(["mock-job-1"]);
  });

  it("cancels a native job whose handle resolves after the Generate page unmounts", async () => {
    let resolveHandle!: (handle: { id: string }) => void;
    const pendingHandle = new Promise<{ id: string }>((resolve) => { resolveHandle = resolve; });
    class DelayedUnmountProvider extends MockDreamProvider {
      readonly cancelledIds: string[] = [];

      override async generate() {
        return pendingHandle;
      }

      override async cancelJob(id: string): Promise<GenerationJob> {
        this.cancelledIds.push(id);
        return { id, request: {} as GenerationRequest, state: "cancelled", progress: 0, message: "已取消生成" };
      }
    }

    const provider = new DelayedUnmountProvider();
    const view = render(<DreamProviderContext.Provider value={provider}><GeneratePage /></DreamProviderContext.Provider>);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
    await act(async () => { await Promise.resolve(); });
    view.unmount();

    await act(async () => {
      resolveHandle({ id: "late-unmounted-job" });
      await Promise.resolve();
    });

    expect(provider.cancelledIds).toEqual(["late-unmounted-job"]);
  });
});
