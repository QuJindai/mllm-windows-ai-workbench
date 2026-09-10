import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LabPage } from "./LabPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { Experiment } from "../../domain/experiment";
import type { ModelRecord } from "../../domain/models";

const model = (id: string, status: ModelRecord["status"]): ModelRecord => ({
  id,
  displayName: id === "ready-model" ? "可用模型" : "不可用模型",
  architecture: "SDXL",
  format: "GGUF",
  dmd2: false,
  path: `E:\\Dream\\models\\${id}.gguf`,
  verified: status === "ready",
  sizeBytes: status === "ready" ? 1024 : 0,
  tags: [],
  description: "测试模型",
  kind: "Checkpoint",
  status,
  imageUrl: "",
});

const runningExperiment: Experiment = {
  id: "experiment-running",
  kind: "fusion",
  seed: 42,
  lockedFields: ["seed", "modelId"],
  status: "running",
  message: "正在按顺序生成",
  variants: [
    { id: "variant-1", jobId: "job-1", modelId: "ready-model", label: "完整提示词（控制组）", state: "queued" },
    { id: "variant-2", jobId: "job-2", modelId: "ready-model", label: "平衡描述改写", state: "preparing" },
    { id: "variant-3", jobId: "job-3", modelId: "ready-model", label: "仅首段提示词", state: "sampling" },
    { id: "variant-4", jobId: "job-4", modelId: "ready-model", label: "重点描述改写", state: "decoding" },
  ],
};

afterEach(() => {
  vi.useRealTimers();
});

describe("Lab page", () => {
  it("uses the current stable profile and keeps semantic experiment controls separate from H7", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><LabPage /></DreamProviderContext.Provider>);

    expect(await screen.findByText(/演示提供方已就绪/)).toBeVisible();
    expect(screen.getByRole("combobox", { name: "步数" })).toHaveValue("20");
    expect(screen.getByRole("combobox", { name: "CFG 缩放" })).toHaveValue("4");
    expect(screen.getByRole("button", { name: "运行实验" })).not.toBeDisabled();
  });

  it("runs a same-seed experiment and renders returned variants", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><LabPage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("button", { name: "运行实验" }));
    expect(await screen.findByText(/实验完成/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "平衡描述改写" })).toBeVisible();
    expect(screen.getAllByText("已完成").length).toBe(4);
  });

  it("promotes a completed experiment into the generation workflow", async () => {
    const onPromote = vi.fn();
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><LabPage onPromote={onPromote} /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("button", { name: "运行实验" }));
    await screen.findByText(/实验完成/);
    fireEvent.click(screen.getByRole("button", { name: "提升为生成预设" }));

    expect(onPromote).toHaveBeenCalledWith(expect.objectContaining({
      modelId: "cyberrealistic-xl-v10-standard",
      seed: 20260906,
      steps: 20,
      cfg: 4,
    }));
  });

  it("marks experiments returned by the mock provider as demo data", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><LabPage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("button", { name: "运行实验" }));

    expect(await screen.findByText("演示数据")).toHaveClass("truth-demo");
    expect(screen.queryByText("实测数据")).not.toBeInTheDocument();
  });

  it("marks experiments returned by the backend provider as observed data", async () => {
    const provider = new MockDreamProvider();
    Object.defineProperty(provider, "mode", { value: "backend" });
    provider.getCapabilities = async () => ({
      nativeGeneration: { available: true, truth: "observed" },
      processTrace: { available: true, truth: "derived" },
      latentTrace: { available: true, truth: "observed" },
      semanticExperiments: { available: true, truth: "observed" },
      attention: { available: false, truth: "unavailable" },
    });
    render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("button", { name: "运行实验" }));

    expect(await screen.findByText("实测数据")).toHaveClass("truth-observed");
    expect(screen.queryByText("演示数据")).not.toBeInTheDocument();
  });

  it("labels prompt-level variants truthfully and excludes unavailable models from comparison", async () => {
    const provider = new MockDreamProvider();
    provider.listModels = async () => [model("ready-model", "ready"), model("missing-model", "unavailable")];
    render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    const experimentType = await screen.findByRole("combobox", { name: "实验类型" });
    const strategy = screen.getByRole("combobox", { name: "比较策略" });

    expect(within(experimentType).getByRole("option", { name: /模型对照/ })).toBeDisabled();
    expect(within(strategy).getByRole("option", { name: /模型对照/ })).toBeDisabled();
    expect(within(screen.getByRole("combobox", { name: "实验模型" })).queryByRole("option", { name: "不可用模型" })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "提示词层对照" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "完整提示词（控制组）" })).toBeVisible();
    expect(screen.queryByText("均值融合")).not.toBeInTheDocument();
    expect(screen.queryByText("Token 加权")).not.toBeInTheDocument();
  });

  it("shows the actual model for each model-comparison variant", async () => {
    const provider = new MockDreamProvider();
    provider.listModels = async () => [model("ready-model", "ready"), model("second-model", "ready")];
    provider.runExperiment = async () => ({
      id: "experiment-models",
      kind: "model",
      seed: 42,
      lockedFields: ["seed"],
      status: "complete",
      variants: [
        { id: "variant-model-1", jobId: "job-model-1", modelId: "ready-model", label: "可用模型", state: "complete" },
        { id: "variant-model-2", jobId: "job-model-2", modelId: "second-model", label: "第二模型", state: "complete" },
      ],
    });
    render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    fireEvent.change(await screen.findByRole("combobox", { name: "实验类型" }), { target: { value: "model" } });
    expect(screen.getByRole("option", { name: /模型对照：固定随机种子/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /固定模型身份/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "运行实验" }));

    expect(await screen.findByText("ready-model")).toBeVisible();
    expect(screen.getByText("second-model")).toBeVisible();
  });

  it("shows each native job state and marks absent metrics unavailable", async () => {
    const provider = new MockDreamProvider();
    provider.runExperiment = async () => runningExperiment;
    provider.getExperiment = async () => runningExperiment;
    render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    fireEvent.click(screen.getByRole("button", { name: "运行实验" }));

    expect(await screen.findByText(/实验进行中/)).toBeVisible();
    expect(screen.getByText("排队中")).toBeVisible();
    expect(screen.getByText("准备中")).toBeVisible();
    expect(screen.getByText("生成中")).toBeVisible();
    expect(screen.getByText("解码中")).toBeVisible();
    expect(screen.getAllByText("不可用（后端未返回）")).toHaveLength(4);
  });

  it("shows the backend capability reason when native experiments are unavailable", async () => {
    const provider = new MockDreamProvider();
    Object.defineProperty(provider, "mode", { value: "backend" });
    provider.getCapabilities = async () => ({
      nativeGeneration: { available: false, truth: "unavailable" },
      processTrace: { available: false, truth: "unavailable" },
      latentTrace: { available: false, truth: "unavailable" },
      semanticExperiments: { available: false, truth: "unavailable", message: "未检测到原生生成依赖" },
      attention: { available: false, truth: "unavailable" },
    });
    provider.listModels = async () => [model("ready-model", "ready")];
    render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    expect(await screen.findByText(/未检测到原生生成依赖/)).toBeVisible();
    expect(screen.getByRole("button", { name: "运行实验" })).toBeDisabled();
  });

  it("keeps polling long serial experiments until terminal state and blocks duplicate submission", async () => {
    vi.useFakeTimers();
    const provider = new MockDreamProvider();
    let polls = 0;
    let submissions = 0;
    provider.runExperiment = async () => {
      submissions += 1;
      return runningExperiment;
    };
    provider.getExperiment = async () => {
      polls += 1;
      return polls > 120
        ? { ...runningExperiment, status: "complete", message: "实验完成" }
        : runningExperiment;
    };
    render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "运行实验" }));
    });
    const activeButton = screen.getByRole("button", { name: "实验运行中…" });
    expect(activeButton).toBeDisabled();
    fireEvent.click(activeButton);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(121 * 1000);
    });

    expect(polls).toBe(121);
    expect(submissions).toBe(1);
    expect(screen.getByText(/实验完成/)).toBeVisible();
    expect(screen.getByRole("button", { name: "运行实验" })).toBeEnabled();
  });

  it("stops polling when the Lab page unmounts", async () => {
    vi.useFakeTimers();
    const provider = new MockDreamProvider();
    let polls = 0;
    provider.runExperiment = async () => runningExperiment;
    provider.getExperiment = async () => {
      polls += 1;
      return runningExperiment;
    };
    const view = render(<DreamProviderContext.Provider value={provider}><LabPage /></DreamProviderContext.Provider>);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "运行实验" }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    const pollsBeforeUnmount = polls;
    view.unmount();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(pollsBeforeUnmount).toBeGreaterThan(0);
    expect(polls).toBe(pollsBeforeUnmount);
  });

  it("switches notebook tabs to their corresponding content", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><LabPage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("tab", { name: "元数据" }));
    expect(await screen.findByText("实验元数据不可用")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "实验标题" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "对比" }));
    expect(screen.getByText("对比输出不可用")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "笔记" }));
    expect(screen.getByRole("textbox", { name: "实验标题" })).toBeVisible();
  });
});
