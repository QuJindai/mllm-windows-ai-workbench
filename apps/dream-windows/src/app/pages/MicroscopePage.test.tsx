import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MicroscopePage } from "./MicroscopePage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { RuntimeAttentionIndex, RuntimeAttentionMap, RuntimeLatentTelemetry, RuntimeTrace } from "../../domain/trace";

function telemetryAt(step: number, deltaL2: number, mean: number): RuntimeLatentTelemetry {
  return {
    step,
    shape: [64, 64, 4, 1],
    mean,
    std: 1 + step / 100,
    l2: 64 + step,
    deltaL2,
    deltaMeanAbs: deltaL2 / 4,
    cosine: 0.99 - step / 1000,
    truth: "observed",
    kind: "latent-state",
    channels: Array.from({ length: 4 }, (_, channel) => ({
      channel,
      fileName: `latent-step-${String(step).padStart(3, "0")}-ch${channel}.png`,
      imageUrl: `/api/traces/job-telemetry/latent/frames/latent-step-${String(step).padStart(3, "0")}-ch${channel}.png`,
      min: -2 - channel / 10,
      max: 2 + channel / 10,
      mean: mean + channel / 100,
      std: 1 + channel / 100,
      l2: 32 + channel,
      histogram: Array.from({ length: 32 }, (_, bin) => bin + channel + 1),
      truth: "observed",
      kind: "latent-channel",
    })),
  };
}

describe("Microscope page", () => {
  it("switches between real runtime records instead of pinning the latest run", async () => {
    class TraceHistoryProvider extends MockDreamProvider {
      readonly requestedRunIds: string[] = [];

      override async listRuntimeTraces() {
        return [
          { runId: "run-new", totalTimeMs: 12000, modelId: "model-new", steps: 20, backend: "CUDA", hasAttention: false, hasLatent: true, modifiedAt: "2026-09-09T12:00:00+00:00", truth: "observed" as const },
          { runId: "run-h7", totalTimeMs: 24000, modelId: "model-h7", steps: 28, backend: "CUDA", hasAttention: true, hasLatent: false, modifiedAt: "2026-09-09T11:00:00+00:00", truth: "observed" as const },
        ];
      }

      override async getRuntimeTrace(runId: string): Promise<RuntimeTrace> {
        this.requestedRunIds.push(runId);
        const resolvedRunId = runId === "latest" ? "run-new" : runId;
        return { available: true, truth: "observed", runId: resolvedRunId, totalTimeMs: resolvedRunId === "run-h7" ? 24000 : 12000, nodes: [], evidence: { modelId: resolvedRunId === "run-h7" ? "model-h7" : "model-new" } };
      }
    }
    const provider = new TraceHistoryProvider();
    render(<DreamProviderContext.Provider value={provider}><MicroscopePage /></DreamProviderContext.Provider>);

    const selector = await screen.findByRole("combobox", { name: "选择运行记录" });
    expect(within(selector).getByRole("option", { name: /H7.*run-h7.*model-h7/ })).toBeVisible();
    fireEvent.change(selector, { target: { value: "run-h7" } });
    await waitFor(() => expect(provider.requestedRunIds).toContain("run-h7"));
    fireEvent.click(screen.getByRole("tab", { name: "专家" }));
    expect(await screen.findByText(/"runId": "run-h7"/)).toBeVisible();
  });

  it("connects all seven microscope tabs to accessible tab panels", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    const tabs = ["运行时", "语义", "条件影响", "潜空间", "机制", "专家", "H7 注意力"];
    expect(await screen.findAllByRole("tab")).toHaveLength(tabs.length);

    for (const label of tabs) {
      const tab = screen.getByRole("tab", { name: label });
      fireEvent.click(tab);
      expect(tab).toHaveAttribute("aria-selected", "true");
      expect(screen.getByRole("tabpanel", { name: label })).toBeVisible();
    }
    expect(await screen.findByText("测试提供方没有原生 H7 注意力张量")).toBeVisible();
  });

  it("supports roving focus with ArrowLeft, ArrowRight, Home, and End", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    const runtime = await screen.findByRole("tab", { name: "运行时" });
    const semantic = screen.getByRole("tab", { name: "语义" });
    const attention = screen.getByRole("tab", { name: "H7 注意力" });
    expect(runtime).toHaveAttribute("tabindex", "0");
    expect(semantic).toHaveAttribute("tabindex", "-1");

    runtime.focus();
    fireEvent.keyDown(runtime, { key: "ArrowRight" });
    expect(semantic).toHaveFocus();
    expect(semantic).toHaveAttribute("aria-selected", "true");
    expect(semantic).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(semantic, { key: "ArrowLeft" });
    expect(runtime).toHaveFocus();
    fireEvent.keyDown(runtime, { key: "ArrowLeft" });
    expect(attention).toHaveFocus();
    fireEvent.keyDown(attention, { key: "Home" });
    expect(runtime).toHaveFocus();
    fireEvent.keyDown(runtime, { key: "End" });
    expect(attention).toHaveFocus();
    expect(screen.getByRole("tabpanel", { name: "H7 注意力" })).toBeVisible();
    expect(await screen.findByText("测试提供方没有原生 H7 注意力张量")).toBeVisible();
  });

  it("renders an unavailable trace response as waiting instead of live data", async () => {
    class UnavailableTraceProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: false,
          runId: "latest",
          message: "No native runtime trace is available",
          truth: "unavailable",
        } as unknown as RuntimeTrace;
      }
    }

    render(<DreamProviderContext.Provider value={new UnavailableTraceProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    expect(await screen.findByText(/等待 native 记录/)).toBeVisible();
    expect(screen.getAllByText("No native runtime trace is available")[0]).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "专家" }));
    expect(screen.getByText("当前 trace · 不可用")).toHaveClass("truth-unavailable");
    expect(screen.queryByText("当前 trace · 实测")).not.toBeInTheDocument();
  });

  it("labels the fixed mock trace as demo in the expert panel", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    expect(await screen.findByText(/固定样例 · 演示/)).toHaveClass("truth-demo");
    expect(screen.getAllByText("数据来自测试提供方固定样例。")[0]).toBeVisible();
    expect(screen.queryByText("数据来自最近一次 native 运行记录。")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "专家" }));

    expect(await screen.findByText(/固定样例 · 演示/)).toHaveClass("truth-demo");
    expect(screen.queryByText("当前 trace · 实测")).not.toBeInTheDocument();
  });

  it("renders measured native phases and opens node evidence", async () => {
    class DetailedTraceProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-measured",
          totalTimeMs: 16000,
          nodes: [
            { id: "conditioning", name: "Conditioning", backend: "CUDA", shape: "text conditioning", durationMs: 3590, status: "executed", truth: "observed" },
            { id: "unet_sampling", name: "UNet sampling", backend: "CUDA", shape: "512 × 512", expectedCalls: 20, durationMs: 8940, status: "executed", truth: "observed" },
            { id: "vae_decode", name: "VAE decode", backend: "CUDA", shape: "latent → RGB", durationMs: 1190, status: "executed", truth: "observed" },
            { id: "generate_image", name: "Image generation", backend: "CUDA", shape: "PNG output", durationMs: 13750, status: "executed", truth: "observed" },
          ],
          events: [
            { phase: "conditioning", label: "Conditioning", durationMs: 3590, truth: "observed" },
            { phase: "unet_sampling", label: "UNet sampling", durationMs: 8940, truth: "observed" },
            { phase: "vae_decode", label: "VAE decode", durationMs: 1190, truth: "observed" },
            { phase: "generate_image", label: "Image generation", durationMs: 13750, truth: "observed" },
          ],
          evidence: { modelId: "test-model", steps: 20, cfg: 7, samplingMethod: "dpm++2m", scheduler: "karras" },
        };
      }
    }

    render(<DreamProviderContext.Provider value={new DetailedTraceProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    expect(await screen.findByText("原生阶段时间线")).toBeVisible();
    expect((await screen.findAllByText("8,940 毫秒"))[0]).toBeVisible();
    expect(screen.queryByText("82%")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "检查 UNet sampling" }));
    await waitFor(() => expect(screen.getByText("预期调用 · 派生")).toBeVisible());
    expect(screen.getByText("20")).toBeVisible();
    expect(screen.getByText("数据来自 stable-diffusion.cpp wrapper 日志。")).toBeVisible();
  });

  it("separates current observed hardware from per-run peak evidence", async () => {
    class HardwareEvidenceProvider extends MockDreamProvider {
      override async getHardware() {
        return {
          gpuName: "Test GPU",
          vramTotalMiB: 6144,
          vramUsedMiB: 1024,
          gpuUtil: 20,
          gpuTempC: 57,
          ramTotalBytes: 64 * 1024 ** 3,
          ramUsedBytes: 8 * 1024 ** 3,
          cudaReady: true,
          dreamRoot: "E:\\Dream",
          truth: "observed",
          isMock: false,
          backend: "stable-diffusion.cpp + CUDA",
          backendTruth: "derived",
        } as HardwareSnapshot & { backend: string; backendTruth: "derived" };
      }

      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-hardware",
          totalTimeMs: 1200,
          nodes: [],
          evidence: { backend: "CUDA FP16", backendTruth: "observed", truth: "observed", peakVramMiB: 2800, peakRamBytes: 4 * 1024 ** 3 },
        };
      }
    }

    render(<DreamProviderContext.Provider value={new HardwareEvidenceProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    const current = (await screen.findByText("当前硬件快照")).closest(".surface-card");
    expect(current).not.toBeNull();
    expect(within(current as HTMLElement).getByText("1,024 / 6,144 MiB")).toBeVisible();
    expect(within(current as HTMLElement).getByText("8.0 / 64.0 GiB")).toBeVisible();
    expect(within(current as HTMLElement).getByText("57 °C")).toBeVisible();
    expect(within(current as HTMLElement).getByText("stable-diffusion.cpp + CUDA")).toBeVisible();
    expect(within(current as HTMLElement).getAllByText("当前 · 实测")).toHaveLength(3);
    expect(within(current as HTMLElement).getByText("检测 · 派生")).toBeVisible();
    expect(within(current as HTMLElement).getByText("检测后端")).toBeVisible();
    expect(screen.getByText("本次运行后端 · 实测")).toBeVisible();
    expect(screen.getByText("CUDA FP16")).toBeVisible();
    expect(screen.getByText("本次运行峰值 VRAM")).toBeVisible();
    expect(screen.getByText("本次运行峰值 RAM")).toBeVisible();
  });

  it("marks an unavailable current GPU temperature instead of rendering null as observed", async () => {
    class MissingTemperatureProvider extends MockDreamProvider {
      override async getHardware() {
        return {
          gpuName: "Test GPU",
          vramTotalMiB: 6144,
          vramUsedMiB: 1024,
          gpuUtil: 20,
          gpuTempC: null,
          ramTotalBytes: 64 * 1024 ** 3,
          ramUsedBytes: 8 * 1024 ** 3,
          cudaReady: true,
          dreamRoot: "E:\\Dream",
          truth: "observed",
          isMock: false,
          backend: "stable-diffusion.cpp + CUDA",
          backendTruth: "derived",
        } as HardwareSnapshot & { gpuTempC: null; backend: string; backendTruth: "derived" };
      }
    }

    render(<DreamProviderContext.Provider value={new MissingTemperatureProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    const current = (await screen.findByText("当前硬件快照")).closest(".surface-card");
    const temperature = within(current as HTMLElement).getByText("当前 GPU 温度").closest("article");
    expect(temperature).not.toBeNull();
    expect(within(temperature as HTMLElement).getByText("—")).toBeVisible();
    expect(within(temperature as HTMLElement).getByText("不可用")).toBeVisible();
    expect(within(temperature as HTMLElement).queryByText("null °C")).not.toBeInTheDocument();
  });

  it("renders only observed runtime nodes, events, and call counts", async () => {
    class RuntimeTruthProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-runtime-truth",
          totalTimeMs: 2000,
          nodes: [
            { id: "observed-node", name: "Observed UNet", backend: "CUDA", expectedCalls: 99, observedCalls: 2, durationMs: 1500, status: "executed", truth: "observed" },
            { id: "derived-node", name: "Derived Scheduler", backend: "CPU", expectedCalls: 20, durationMs: 300, status: "executed", truth: "derived" },
          ],
          events: [
            { phase: "observed-node", label: "Observed UNet", durationMs: 1500, truth: "observed" },
            { phase: "derived-node", label: "Derived Scheduler", durationMs: 300, truth: "derived" },
          ],
        };
      }
    }

    render(<DreamProviderContext.Provider value={new RuntimeTruthProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("button", { name: "检查 Observed UNet" }));
    expect(screen.getByText("实际调用 · 实测")).toBeVisible();
    expect(screen.getAllByText("2")[0]).toBeVisible();
    expect(screen.getByText("预期调用 · 派生")).toBeVisible();
    expect(screen.queryByRole("button", { name: "检查 Derived Scheduler" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Derived Scheduler" })).not.toBeInTheDocument();
  });

  it("renders a step scrubber from observed latent projection frames", async () => {
    class LatentProjectionProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-latent-projection",
          totalTimeMs: 3000,
          nodes: [],
          latentPreviewFrames: [
            { step: 0, fileName: "latent-step-000.png", imageUrl: "/api/traces/job-latent-projection/latent/frames/latent-step-000.png", truth: "observed", kind: "latent-projection" },
            { step: 1, fileName: "latent-step-001.png", imageUrl: "/api/traces/job-latent-projection/latent/frames/latent-step-001.png", truth: "observed", kind: "latent-projection" },
          ],
        };
      }
    }

    render(<DreamProviderContext.Provider value={new LatentProjectionProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    expect(await screen.findByText("Latent 投影预览")).toBeVisible();
    expect(screen.getByText("第 1 / 2 步")).toBeVisible();
    expect(screen.getByRole("img", { name: "Latent 投影第 1 步" })).toHaveAttribute("src", "/api/traces/job-latent-projection/latent/frames/latent-step-000.png");
    expect(screen.getByText("原始 latent 通道不可用")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "下一个 latent 步骤" }));
    expect(screen.getByText("第 2 / 2 步")).toBeVisible();
    expect(screen.getByRole("img", { name: "Latent 投影第 2 步" })).toHaveAttribute("src", "/api/traces/job-latent-projection/latent/frames/latent-step-001.png");
  });

  it("renders observed process dynamics and four-channel latent inspector data", async () => {
    class LatentTelemetryProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-latent-telemetry",
          totalTimeMs: 3000,
          nodes: [],
          latentTelemetry: [{
            step: 0,
            shape: [64, 64, 4, 1],
            mean: -0.0031,
            std: 1.0276,
            l2: 65.43,
            deltaL2: 0.0483,
            deltaMeanAbs: 0.0127,
            cosine: 0.9981,
            truth: "observed",
            kind: "latent-state",
            channels: Array.from({ length: 4 }, (_, channel) => ({
              channel,
              fileName: `latent-step-000-ch${channel}.png`,
              imageUrl: `/api/traces/job-latent-telemetry/latent/frames/latent-step-000-ch${channel}.png`,
              min: -2.3,
              max: 2.2,
              mean: -0.01,
              std: 1.02,
              l2: 65.4,
              histogram: Array.from({ length: 32 }, () => 1),
              truth: "observed",
              kind: "latent-channel",
            })),
          }],
        } as unknown as RuntimeTrace;
      }
    }

    render(<DreamProviderContext.Provider value={new LatentTelemetryProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    expect(await screen.findByText("过程动态")).toBeVisible();
    expect(screen.getByText("Δz L2")).toBeVisible();
    expect(screen.getByText("0.0483")).toBeVisible();
    expect(screen.getByText("Latent 状态检查器")).toBeVisible();
    expect(screen.getByText("通道 C0")).toBeVisible();
    expect(screen.getByText("直方图")).toBeVisible();
    expect(screen.getByText("上一步 / 当前 / 最终")).toBeVisible();
    expect(screen.getByRole("img", { name: "通道 C3" })).toHaveAttribute("src", "/api/traces/job-latent-telemetry/latent/frames/latent-step-000-ch3.png");
    expect(screen.queryByText("原始 latent 通道不可用")).not.toBeInTheDocument();
  });

  it("rejects four unique channels unless they are exactly C0 through C3", async () => {
    class WrongChannelIdsProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        const sample = telemetryAt(0, 0.1, 0);
        sample.channels = sample.channels.map((channel) => ({ ...channel, channel: channel.channel + 4 }));
        return { available: true, truth: "observed", runId: "job-wrong-channels", totalTimeMs: 1000, nodes: [], latentTelemetry: [sample] };
      }
    }

    render(<DreamProviderContext.Provider value={new WrongChannelIdsProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    expect(await screen.findByText("四通道 Latent 检查器不可用")).toBeVisible();
    expect(screen.queryByRole("img", { name: "通道 C4 直方图" })).not.toBeInTheDocument();
  });

  it("uses telemetry steps for a bounded selector and previous-current-final comparison", async () => {
    class TelemetryOnlyProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-telemetry",
          totalTimeMs: 3000,
          nodes: [],
          latentPreviewFrames: [],
          latentTelemetry: [telemetryAt(0, 0.1111, -0.01), telemetryAt(4, 0.2222, 0.02), telemetryAt(7, 0.3333, 0.05)],
        };
      }
    }

    render(<DreamProviderContext.Provider value={new TelemetryOnlyProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    const selector = await screen.findByRole("slider", { name: "Latent 遥测步骤" });
    expect(selector).toHaveAttribute("min", "0");
    expect(selector).toHaveAttribute("max", "2");
    fireEvent.change(selector, { target: { value: "1" } });
    expect(screen.getByText("0.2222")).toBeVisible();
    expect(within(screen.getByLabelText("上一步 Latent")).getByText("第 1 步")).toBeVisible();
    expect(within(screen.getByLabelText("当前 Latent")).getByText("第 5 步")).toBeVisible();
    expect(within(screen.getByLabelText("最终 Latent")).getByText("第 8 步")).toBeVisible();
    expect(screen.getAllByRole("img", { name: /通道 C\d 直方图/ })).toHaveLength(4);
    fireEvent.change(selector, { target: { value: "2" } });
    expect(screen.getByRole("button", { name: "下一个遥测步骤" })).toBeDisabled();
  });

  it("keeps the observed telemetry selector independent from the projection selector", async () => {
    class IndependentSelectorsProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-independent-selectors",
          totalTimeMs: 1000,
          nodes: [],
          latentPreviewFrames: [0, 1, 2].map((step) => ({ step, fileName: `latent-step-00${step}.png`, truth: "observed" as const, kind: "latent-projection" as const })),
          latentTelemetry: [telemetryAt(0, 0.1, 0), telemetryAt(4, 0.2, 0), telemetryAt(7, 0.3, 0)],
        };
      }
    }

    render(<DreamProviderContext.Provider value={new IndependentSelectorsProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    const telemetrySelector = await screen.findByRole("slider", { name: "Latent 遥测步骤" });
    const projectionSelector = screen.getByRole("slider", { name: "Latent 预览步骤" });
    fireEvent.change(projectionSelector, { target: { value: "2" } });
    expect(telemetrySelector).toHaveValue("0");
    fireEvent.change(telemetrySelector, { target: { value: "1" } });
    expect(projectionSelector).toHaveValue("2");
  });

  it("shows channel correlation as unavailable when no observed matrix was exported", async () => {
    class NoCorrelationProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return { available: true, runId: "job-no-correlation", totalTimeMs: 1000, nodes: [], latentTelemetry: [telemetryAt(0, 0.1, 0)] };
      }
    }

    render(<DreamProviderContext.Provider value={new NoCorrelationProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    expect(await screen.findByText("通道相关性不可用")).toBeVisible();
    expect(screen.getByText("当前 trace 未导出实测的 4 × 4 通道相关矩阵。")).toBeVisible();
  });

  it("loads microscope projection and channel images lazily and asynchronously", async () => {
    class ImageLoadingProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return {
          available: true,
          runId: "job-images",
          totalTimeMs: 1000,
          nodes: [],
          latentPreviewFrames: [{ step: 0, fileName: "latent-step-000.png", imageUrl: "/latent-step-000.png", truth: "observed", kind: "latent-projection" }],
          latentTelemetry: [telemetryAt(0, 0.1, 0)],
        };
      }
    }

    render(<DreamProviderContext.Provider value={new ImageLoadingProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));

    const images = Array.from(screen.getByRole("tabpanel", { name: "潜空间" }).querySelectorAll("img"));
    expect(images.length).toBeGreaterThan(0);
    for (const image of images) {
      expect(image).toHaveAttribute("loading", "lazy");
      expect(image).toHaveAttribute("decoding", "async");
    }
  });

  it("shares validated H7 tokenizer evidence with the semantic and expert panels", async () => {
    class SharedH7EvidenceProvider extends MockDreamProvider {
      attentionIndexCalls = 0;

      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return { available: true, truth: "observed", runId: "run-h7-shared", totalTimeMs: 1200, nodes: [] };
      }

      override async getAttentionIndex(): Promise<RuntimeAttentionIndex> {
        this.attentionIndexCalls += 1;
        return {
          available: true,
          runId: "run-h7-shared",
          contractVersion: "h7-attention-v1",
          kind: "cross-attention",
          truth: "observed",
          source: "debug-unet",
          tokens: [
            { slot: 1, tokenId: 2553, text: "lake", chunk: 0, weight: 0.75 },
            { slot: 2, tokenId: 9001, text: "sunrise", chunk: 1, weight: 1 },
          ],
          layers: [
            { id: "down-1", stage: "down", label: "Down 1" },
            { id: "mid-1", stage: "mid", label: "Mid 1" },
          ],
          maps: [
            { id: "lake-down", step: 0, layerId: "down-1", tokenSlot: 1, width: 2, height: 2, entropy: 0.7, peak: 0.8, coverage: 0.2, mapUrl: "/lake-down" },
            { id: "sunrise-mid", step: 4, layerId: "mid-1", tokenSlot: 2, width: 2, height: 2, entropy: 0.6, peak: 0.9, coverage: 0.3, mapUrl: "/sunrise-mid" },
          ],
        };
      }
    }

    const provider = new SharedH7EvidenceProvider();
    render(<DreamProviderContext.Provider value={provider}><MicroscopePage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("tab", { name: "语义" }));
    const semanticPanel = screen.getByRole("tabpanel", { name: "语义" });
    expect(await within(semanticPanel).findByText("H7 tokenizer · 实测")).toBeVisible();
    const tokenList = within(semanticPanel).getByRole("list", { name: "实测 Token 列表" });
    expect(within(tokenList).getByText("lake")).toBeVisible();
    expect(within(tokenList).getByText("ID 2553")).toBeVisible();
    expect(within(tokenList).getByText("权重 0.75")).toBeVisible();
    expect(within(semanticPanel).getByRole("group", { name: "实测 Chunk 列表" })).toHaveTextContent("Chunk 2sunrise1 个 token");
    expect(within(semanticPanel).queryByText("原始 token 不可用")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "专家" }));
    const expertPanel = screen.getByRole("tabpanel", { name: "专家" });
    expect(await within(expertPanel).findByText("H7 attention 张量：2 张实测图")).toBeVisible();
    expect(within(expertPanel).getByText("H7 attention 索引")).toBeVisible();
    expect(provider.attentionIndexCalls).toBe(1);
  });

  it("keeps raw token, chunk, and H6 influence data explicitly unavailable", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("tab", { name: "语义" }));
    expect(screen.getByText("原始 token 不可用")).toBeVisible();
    expect(screen.getByText("原始 chunk 不可用")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "条件影响" }));
    expect(screen.getByText("H6 条件影响张量不可用")).toBeVisible();
    expect(screen.getByText("这是 chunk prediction 相对 fused prediction 的差异，不是 cross-attention。")).toBeVisible();
  });

  it("uses H7 capability and research reasons but stays unavailable without tensors", async () => {
    class H7WithoutTensorsProvider extends MockDreamProvider {
      override async getCapabilities() {
        const capabilities = await super.getCapabilities();
        return { ...capabilities, attention: { available: true, truth: "observed" as const, message: "Debug UNet Graph 已声明 attention 能力" } };
      }

      override async getResearchStatus() {
        return { available: true, message: "研究引擎已连接", truth: "observed" as const };
      }
    }

    render(<DreamProviderContext.Provider value={new H7WithoutTensorsProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "H7 注意力" }));

    const panel = screen.getByRole("tabpanel", { name: "H7 注意力" });
    expect(await within(panel).findByText("Debug UNet Graph 已声明 attention 能力")).toBeVisible();
    expect(within(panel).getByText("研究引擎已连接")).toBeVisible();
    expect(within(panel).getByText("Attention 张量不可用")).toBeVisible();
    expect(within(panel).getByText("能力和研究引擎已就绪，但当前 trace 没有导出 attention 张量。")).toBeVisible();
    expect(within(panel).queryByRole("img")).not.toBeInTheDocument();
    expect(panel.querySelector("canvas, [data-attention-heatmap]")).toBeNull();
  });

  it("renders validated H7 token-layer-step maps and updates the measured heatmap selection", async () => {
    class H7AttentionProvider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return { available: true, truth: "observed", runId: "run-h7", totalTimeMs: 1000, nodes: [] };
      }

      override async getCapabilities() {
        const capabilities = await super.getCapabilities();
        return { ...capabilities, attention: { available: true, truth: "observed" as const, message: "H7 Debug UNet 已连接" } };
      }

      override async getResearchStatus() {
        return { available: true, message: "H7 研究引擎已就绪", truth: "observed" as const };
      }

      override async getAttentionIndex(): Promise<RuntimeAttentionIndex> {
        return {
          available: true,
          runId: "run-h7",
          contractVersion: "h7-attention-v1",
          kind: "cross-attention",
          truth: "observed",
          source: "debug-unet",
          tokens: [
            { slot: 1, tokenId: 320, text: "lake", chunk: 0, weight: 1 },
            { slot: 2, tokenId: 700, text: "mountain", chunk: 0, weight: 1 },
          ],
          layers: [
            { id: "down-1", stage: "down", label: "Down 1" },
            { id: "mid-1", stage: "mid", label: "Mid 1" },
          ],
          maps: [
            { id: "lake-down", step: 0, layerId: "down-1", tokenSlot: 1, width: 2, height: 2, entropy: 0.7, peak: 0.8, coverage: 0.2, mapUrl: "/lake-down" },
            { id: "mountain-mid", step: 4, layerId: "mid-1", tokenSlot: 2, width: 2, height: 2, entropy: 0.61, peak: 0.92, coverage: 0.31, mapUrl: "/mountain-mid" },
          ],
        };
      }

      override async getAttentionMap(_runId: string, mapId: string): Promise<RuntimeAttentionMap> {
        const mountain = mapId === "mountain-mid";
        return {
          available: true,
          runId: "run-h7",
          contractVersion: "h7-attention-v1",
          kind: "cross-attention",
          truth: "observed",
          source: "debug-unet",
          id: mapId,
          step: mountain ? 4 : 0,
          layerId: mountain ? "mid-1" : "down-1",
          tokenSlot: mountain ? 2 : 1,
          width: 2,
          height: 2,
          entropy: mountain ? 0.61 : 0.7,
          peak: mountain ? 0.92 : 0.8,
          coverage: mountain ? 0.31 : 0.2,
          values: mountain ? [0.1, 0.4, 0.7, 1] : [0, 0.2, 0.5, 0.8],
        };
      }
    }

    render(<DreamProviderContext.Provider value={new H7AttentionProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "H7 注意力" }));

    expect(await screen.findByText("H7 注意力工作台")).toBeVisible();
    const lakeMap = screen.getByRole("img", { name: "lake 在 Down 1 第 1 步的注意力热力图" });
    expect(lakeMap).toHaveAttribute("data-attention-heatmap", "observed");
    expect(lakeMap.querySelector("span:first-child")).toHaveAttribute("data-display-intensity", "0.0000");
    expect(lakeMap.querySelector("span:last-child")).toHaveAttribute("data-display-intensity", "1.0000");
    expect(screen.getByText("色阶按当前图实测范围 0.0000–0.8000 归一化")).toBeVisible();
    expect(screen.getByText("0.800")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "选择 token mountain" }));
    expect(await screen.findByRole("img", { name: "mountain 在 Mid 1 第 5 步的注意力热力图" })).toBeVisible();
    expect(screen.getByText("0.920")).toBeVisible();
  });

  it("exposes the mobile microscope sections with honest evidence boundaries", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><MicroscopePage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("tab", { name: "语义" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "条件影响" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "机制" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "专家" })).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "语义" }));
    expect(screen.getByText("提示词与分块")).toBeVisible();
    expect(screen.getByText("CFG 引导链路")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "条件影响" }));
    expect(screen.getByText("H6 条件影响")).toBeVisible();
    expect(screen.getByText(/当前 native 记录没有导出条件影响张量/)).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "机制" }));
    expect(screen.getByText("可验证的计算关系")).toBeVisible();
    expect(screen.getByText("观察值优先")).toBeVisible();

    fireEvent.click(screen.getByRole("tab", { name: "专家" }));
    expect(screen.getByText("原始运行记录")).toBeVisible();
    expect(screen.getByText(/不会把推测当作实测/)).toBeVisible();
    expect(await screen.findByText("测试提供方没有原生 H7 注意力张量")).toBeVisible();
  });
});
