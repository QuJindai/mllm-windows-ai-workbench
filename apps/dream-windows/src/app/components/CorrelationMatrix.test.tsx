import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuntimeLatentTelemetry } from "../../domain/trace";
import { CorrelationMatrix } from "./CorrelationMatrix";

const base: RuntimeLatentTelemetry = {
  step: 6, shape: [2, 2, 2, 1], mean: 0, std: 1, l2: 2,
  channels: [], truth: "observed", kind: "latent-state",
};

describe("CorrelationMatrix", () => {
  it("renders signed and zero Pearson values with row and column headers", () => {
    render(<CorrelationMatrix sample={{ ...base, correlationMethod: "pearson", channelCorrelation: [[1, 0], [0, 1]] }} />);
    const table = screen.getByRole("table", { name: "第 7 步 · Pearson 通道相关矩阵" });
    expect(within(table).getByRole("rowheader", { name: "C0" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "C1" })).toBeVisible();
    expect(within(table).getByRole("cell", { name: "C0 与 C1：0.0000" })).toHaveTextContent("0.0000");
  });

  it("keeps constant diagonals undefined and clears old data on rerender", () => {
    const { rerender } = render(<CorrelationMatrix sample={{ ...base, correlationMethod: "pearson", channelCorrelation: [[null, null], [null, null]] }} />);
    expect(screen.getByRole("cell", { name: "C0 与 C0：未定义" })).toHaveTextContent("—");
    expect(screen.queryByText("1.0000")).not.toBeInTheDocument();
    rerender(<CorrelationMatrix sample={base} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("通道相关性不可用")).toBeVisible();
  });

  it("accepts floating roundoff on the identity collector's Pearson diagonal", () => {
    render(<CorrelationMatrix sample={{ ...base, correlationMethod: "pearson", channelCorrelation: [[.9999999999999998, .5], [.5, 1]] }} />);
    expect(screen.getByRole("cell", { name: "C0 与 C1：0.5000" })).toBeVisible();
  });

  it.each([
    [], [[1]], [[1, .5], [-.5, 1]], [[1, 1.1], [1.1, 1]],
    [[1, NaN], [NaN, 1]], [[1, Infinity], [Infinity, 1]],
    [[null, 0], [0, 1]], [[0, 0], [0, 1]], [[1, null], [null, 1]],
  ].map((matrix) => ({ matrix })))("does not label malformed matrices as measured: %j", ({ matrix }) => {
    render(<CorrelationMatrix sample={{ ...base, correlationMethod: "pearson", channelCorrelation: matrix }} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("通道相关性不可用")).toBeVisible();
  });
});
