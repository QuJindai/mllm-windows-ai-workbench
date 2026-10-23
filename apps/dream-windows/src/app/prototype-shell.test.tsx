import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { DreamProviderContext } from "./providers";
import { MockDreamProvider } from "../providers/MockDreamProvider";

describe("prototype workstation shell", () => {
  it("renders the Dream top bar, resource metrics, path, and prototype navigation", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><App /></DreamProviderContext.Provider>);

    await waitFor(() => expect(screen.getAllByText("Dream").length).toBeGreaterThan(0));
    expect(screen.getByText("本地 AI · 更深的想象")).toBeVisible();
    expect(screen.getByText("E:\\Dream")).toBeVisible();
    expect(await screen.findByText("RTX 1000 Ada 6GB")).toBeVisible();
    expect(screen.getByText((_, element) => Boolean(element?.classList.contains("top-metric") && element.textContent?.includes("RAM 64 GB")))).toBeVisible();
  });

  it("renders real page structures instead of route placeholders", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><App /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "生成" });

    fireEvent.click(screen.getByRole("button", { name: "实验室" }));
    expect(screen.getByText("实验记录本")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "显微镜" }));
    expect(screen.getByText("运行时计算图")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    expect((await screen.findAllByText("工作区路径")).length).toBeGreaterThan(0);
  });
});
