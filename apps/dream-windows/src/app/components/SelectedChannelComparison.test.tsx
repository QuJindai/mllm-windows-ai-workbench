import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuntimeLatentTelemetry, RuntimeLatentChannel } from "../../domain/trace";
import { SelectedChannelComparison } from "./SelectedChannelComparison";

const channel: RuntimeLatentChannel = { channel: 2, fileName: "channel.png", min: -3, max: 5,
  mean: 1, std: 2, l2: 7, histogram: [], truth: "observed", kind: "latent-channel" };
const current: RuntimeLatentTelemetry = { step: 7, shape: [2, 2, 4, 1], mean: 999,
  std: 999, l2: 999, channels: [channel], truth: "observed", kind: "latent-state" };

describe("SelectedChannelComparison", () => {
  it("compares the selected channel's complete metrics, not global or positional channel data", () => {
    render(<SelectedChannelComparison previous={{ ...current, step: 2, channels: [{ ...channel, mean: -2 }] }}
      current={{ ...current, channels: [{ ...channel, channel: 0, mean: 800 }, channel] }}
      final={{ ...current, step: 9, channels: [{ ...channel, min: -9, max: 11, mean: 3, std: 4, l2: 13 }] }} />);
    fireEvent.change(screen.getByRole("combobox", { name: "选择对比通道" }), { target: { value: "2" } });
    const table = screen.getByRole("table", { name: "C2 上一步、当前与最终统计" });
    const cells = (name: RegExp) => within(within(table).getByRole("row", { name })).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells(/上一步 第 3 步/)).toEqual(["-3.0000", "5.0000", "-2.0000", "2.0000", "7.0000"]);
    expect(cells(/当前 第 8 步/)).toEqual(["-3.0000", "5.0000", "1.0000", "2.0000", "7.0000"]);
    expect(cells(/最终 第 10 步/)).toEqual(["-9.0000", "11.0000", "3.0000", "4.0000", "13.0000"]);
    expect(within(table).queryByText("999.0000")).not.toBeInTheDocument();
  });

  it("distinguishes an absent previous step from a missing channel without retaining stale values", () => {
    const { rerender } = render(<SelectedChannelComparison current={current} final={{ ...current, channels: [] }} />);
    expect(screen.getByText("尚未采集")).toBeVisible();
    expect(screen.getByText("通道未采集")).toBeVisible();
    rerender(<SelectedChannelComparison current={{ ...current, channels: [] }} final={{ ...current, channels: [] }} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("通道对比不可用")).toBeVisible();
  });
});
