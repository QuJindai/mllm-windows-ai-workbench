import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { DreamProviderContext } from "./providers";
import { MockDreamProvider } from "../providers/MockDreamProvider";

describe("Dream navigation shell", () => {
  it("switches between the six workstation routes", async () => {
    const provider = new MockDreamProvider();
    render(
      <DreamProviderContext.Provider value={provider}>
        <App />
      </DreamProviderContext.Provider>,
    );

    await waitFor(() => expect(screen.getByText("演示 / 模拟")).toBeInTheDocument());
    for (const [label, heading] of [
      ["生成", "生成"],
      ["模型", "模型"],
      ["历史", "历史"],
      ["实验室", "语义实验室"],
      ["显微镜", "显微镜"],
      ["设置", "设置"],
    ]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
      if (label === "设置") {
        expect(await screen.findByRole("tablist", { name: "设置分区" })).toBeInTheDocument();
      }
    }
  });
});
