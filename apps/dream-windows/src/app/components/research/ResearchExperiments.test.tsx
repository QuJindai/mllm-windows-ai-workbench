import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CrossRunComparison } from "./CrossRunComparison";
import { MobileFusionExperiment } from "./MobileFusionExperiment";

const provenance = (runId: string) => ({ runId, modelId: "model-a", backend: "CUDA", samplingMethod: "euler", scheduler: "karras", steps: 20, cfg: 4, source: `/api/traces/${runId}`, metricSource: "latentTelemetry", truth: "observed", recordSha256: "a".repeat(64) });
const comparison = {
  contractVersion: "latent-run-comparison-v1", truth: "derived", scope: "descriptive-recorded-latent-statistics",
  coverage: { capturedSteps: [0], capturedCount: 1, configuredSteps: 20 },
  provenance: { left: provenance("run-a"), right: provenance("run-b") },
  rows: [{ step: 0, metric: "mean", left: 1, right: 5, delta: 4 },
    { step: 0, metric: "std", left: 2, right: 2, delta: 0 },
    { step: 0, metric: "l2", left: 3, right: 3, delta: 0 }],
  limitations: "记录统计对照，不代表相似度或画质。",
};
const runs = [{ runId: "run-a" }, { runId: "run-b" }, { runId: "run-c" }];
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => vi.unstubAllGlobals());

describe("Cross-run microscope comparison", () => {
  it("shows recorded values, source and exact coverage then clears rejected comparisons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(comparison))
      .mockResolvedValueOnce(response({ message: "采集覆盖不一致" }, 422)));
    render(<CrossRunComparison runId="run-a" runs={runs} />);
    fireEvent.change(screen.getByLabelText("对照运行"), { target: { value: "run-b" } });
    fireEvent.click(screen.getByRole("button", { name: "比较实测指标" }));
    const table = await screen.findByRole("table", { name: "跨运行潜变量统计" });
    expect(within(table).getByRole("row", { name: /0.*均值.*1.0000.*5.0000.*4.0000/ })).toBeVisible();
    expect(screen.getByText(/已采集 1 个步号.*配置 20 步/)).toBeVisible();
    expect(screen.getByText(/CUDA.*euler.*karras/)).toBeVisible();
    expect(screen.getAllByText("a".repeat(64))).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("对照运行"), { target: { value: "run-c" } });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "比较实测指标" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("采集覆盖不一致");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("ignores an old response after changing the current run", async () => {
    let complete!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>(resolve => { complete = resolve; })));
    const { rerender } = render(<CrossRunComparison runId="run-a" runs={runs} />);
    fireEvent.change(screen.getByLabelText("对照运行"), { target: { value: "run-b" } });
    fireEvent.click(screen.getByRole("button", { name: "比较实测指标" }));
    rerender(<CrossRunComparison runId="run-c" runs={runs} />);
    await act(async () => { complete(response(comparison)); });
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rejects incomplete response metrics instead of drawing invented values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...comparison, rows: [{ ...comparison.rows[0], left: null }] })));
    render(<CrossRunComparison runId="run-a" runs={runs} />);
    fireEvent.change(screen.getByLabelText("对照运行"), { target: { value: "run-b" } });
    fireEvent.click(screen.getByRole("button", { name: "比较实测指标" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/无效/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("rejects a response whose provenance changes engines", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...comparison,
      provenance: { ...comparison.provenance, right: { ...comparison.provenance.right, backend: "other-engine" } } })));
    render(<CrossRunComparison runId="run-a" runs={runs} />);
    fireEvent.change(screen.getByLabelText("对照运行"), { target: { value: "run-b" } });
    fireEvent.click(screen.getByRole("button", { name: "比较实测指标" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/无效/);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("Mobile prediction fusion", () => {
  it("can retry after closing a pending replay and never restores its late response", async () => {
    let finish!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(response({ available: true, execution: "cpu-import-replay", nativeGenerationAvailable: false }))
      .mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }))
      .mockResolvedValueOnce(response({ available: true, execution: "cpu-import-replay", nativeGenerationAvailable: false })));
    render(<MobileFusionExperiment />);
    const toggle = screen.getByRole("button", { name: "手机 chunk 预测融合" });
    fireEvent.click(toggle);
    const file = new File(['{}'], "prediction.json");
    Object.defineProperty(file, "text", { value: async () => '{}' });
    fireEvent.change(screen.getByLabelText("导入成对预测 JSON"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "执行 CPU 融合重放" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "执行 CPU 融合重放" }));
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    await act(async () => { finish(response({ message: "old error" }, 422)); });
    await waitFor(() => expect(screen.getByRole("button", { name: "执行 CPU 融合重放" })).toBeEnabled());
    expect(screen.queryByText("old error")).not.toBeInTheDocument();
  });

  it("imports a tensor file and shows derived arithmetic with the device verification boundary", async () => {
    const result = {
      contractVersion: "mobile-chunk-fusion-replay-v1", truth: "derived", execution: "cpu-import-replay",
      shape: [2], cfg: 2, alpha: .25, chunkCount: 2, skippedUnconditional: false,
      provenance: { runId: "phone-run-1", modelId: "model-a", engine: "android-qnn", engineRevision: "build-a", step: 0,
        capturedAt: "2026-10-29T00:00:00Z", inputSha256: "b".repeat(64), inputVerification: "imported-unverified" },
      variants: ["first_only", "equal_mean", "token_weighted", "anchor_residual"].map(mode => ({ mode,
        weights: [.5, .5], prediction: [6.5, 9.5], meanAbs: 8, l2: 11, deltaL2FromEqualMean: 0, cosineToEqualMean: null })),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response({ available: true, execution: "cpu-import-replay", nativeGenerationAvailable: false, maxBodyBytes: 12582912 }))
      .mockResolvedValueOnce(response(result)));
    render(<MobileFusionExperiment />);
    fireEvent.click(screen.getByRole("button", { name: "手机 chunk 预测融合" }));
    const run = await screen.findByRole("button", { name: "执行 CPU 融合重放" });
    expect(run).toBeDisabled();
    const file = new File(['{"test":true}'], "prediction.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => '{"test":true}' });
    fireEvent.change(screen.getByLabelText("导入成对预测 JSON"), { target: { files: [file] } });
    await waitFor(() => expect(run).toBeEnabled());
    fireEvent.click(run);
    expect(await screen.findByRole("table", { name: "预测融合数值对照" })).toBeVisible();
    expect(screen.getByText(/导入来源未经设备验证/)).toBeVisible();
    expect(screen.getByText(/phone-run-1/)).toBeVisible();
    expect(screen.getByText("b".repeat(64))).toBeVisible();
    expect(screen.getAllByText("未定义（零范数）")).toHaveLength(4);
  });

  it("leaves replay unavailable if the server does not expose the CPU capability", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ available: false })));
    render(<MobileFusionExperiment />);
    fireEvent.click(screen.getByRole("button", { name: "手机 chunk 预测融合" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/不可用/);
    expect(screen.getByRole("button", { name: "执行 CPU 融合重放" })).toBeDisabled();
  });
});
