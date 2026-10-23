import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MicroscopePage } from "./MicroscopePage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { RuntimeLatentTelemetry, RuntimeTrace } from "../../domain/trace";

function sample(step: number, correlation?: (number | null)[][]): RuntimeLatentTelemetry {
  return {
    step, shape: [3, 1, 3, 2], mean: 0, std: 1, l2: 3,
    truth: "observed", kind: "latent-state",
    ...(correlation ? { channelCorrelation: correlation, correlationMethod: "pearson" as const } : {}),
    channels: [0, 1, 2].map((channel) => ({
      channel, fileName: `latent-step-${step}-ch${channel}.png`, min: -1, max: 1,
      mean: 0, std: channel === 2 ? 0 : 1, l2: 2, histogram: [3, ...Array(31).fill(0)],
      truth: "observed", kind: "latent-channel",
    })),
  };
}

describe("microscope latent correlation", () => {
  it("shows each step's delta image and selected-channel previous/current/final statistics", async () => {
    class Provider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return { runId: "delta", totalTimeMs: 0, nodes: [], latentTelemetry: [2, 7, 9].map((step) => ({
          ...sample(step),
          ...(step > 2 ? { deltaImageUrl: `/api/traces/delta/latent/frames/latent-step-00${step}-delta.png` } : {}),
          channels: sample(step).channels.map((channel) => ({ ...channel, mean: step * 10 + channel.channel,
            std: step + channel.channel, min: -step - channel.channel, max: step + channel.channel, l2: step * 100 + channel.channel })),
        })) };
      }
    }
    render(<DreamProviderContext.Provider value={new Provider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));
    expect(await screen.findByText("空间 Δz 图不可用")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "下一个遥测步骤" }));
    expect(screen.getByRole("img", { name: "第 8 步空间平均 |Δz|" })).toHaveAttribute("src", "/api/traces/delta/latent/frames/latent-step-007-delta.png");
    fireEvent.change(screen.getByRole("combobox", { name: "选择对比通道" }), { target: { value: "1" } });
    let table = screen.getByRole("table", { name: "C1 上一步、当前与最终统计" });
    expect(within(table).getByRole("row", { name: /上一步 第 3 步/ })).toHaveTextContent("21.0000");
    expect(within(table).getByRole("row", { name: /当前 第 8 步/ })).toHaveTextContent("71.0000");
    expect(within(table).getByRole("row", { name: /最终 第 10 步/ })).toHaveTextContent("91.0000");
    fireEvent.click(screen.getByRole("button", { name: "下一个遥测步骤" }));
    expect(screen.queryByRole("img", { name: "第 8 步空间平均 |Δz|" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "第 10 步空间平均 |Δz|" })).toHaveAttribute("src", "/api/traces/delta/latent/frames/latent-step-009-delta.png");
    table = screen.getByRole("table", { name: "C1 上一步、当前与最终统计" });
    expect(within(table).getByRole("row", { name: /上一步 第 8 步/ })).toHaveTextContent("71.0000");
    fireEvent.change(screen.getByRole("slider", { name: "Latent 遥测步骤" }), { target: { value: "0" } });
    expect(screen.getByText("空间 Δz 图不可用")).toBeVisible();
    expect(screen.queryByRole("img", { name: /空间平均/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "C1 上一步、当前与最终统计" })).getByRole("row", { name: /上一步/ })).toHaveTextContent("尚未采集");
  });

  it("uses actual sparse telemetry steps and clears the matrix on an old sample", async () => {
    class Provider extends MockDreamProvider {
      override async getRuntimeTrace(): Promise<RuntimeTrace> {
        return { runId: "correlation", totalTimeMs: 0, nodes: [], latentTelemetry: [
          sample(2, [[1, .5, null], [.5, 1, null], [null, null, null]]),
          sample(7, [[1, -1, null], [-1, 1, null], [null, null, null]]),
          sample(9),
        ] };
      }
    }
    render(<DreamProviderContext.Provider value={new Provider()}><MicroscopePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "潜空间" }));
    let table = await screen.findByRole("table", { name: /第 3 步.*Pearson/ });
    expect(within(table).getByRole("cell", { name: "C0 与 C1：0.5000" })).toBeVisible();
    expect(within(table).getByRole("cell", { name: "C2 与 C2：未定义" })).toHaveTextContent("—");
    fireEvent.click(screen.getByRole("button", { name: "下一个遥测步骤" }));
    table = screen.getByRole("table", { name: /第 8 步.*Pearson/ });
    expect(within(table).getByRole("cell", { name: "C0 与 C1：-1.0000" })).toBeVisible();
    fireEvent.change(screen.getByRole("slider", { name: "Latent 遥测步骤" }), { target: { value: "2" } });
    expect(screen.queryByRole("table", { name: /Pearson/ })).not.toBeInTheDocument();
    expect(screen.getByText("通道相关性不可用")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "上一个遥测步骤" }));
    expect(screen.getByRole("table", { name: /第 8 步.*Pearson/ })).toBeVisible();
  });
});
