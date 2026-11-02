import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { DreamProviderContext } from "./providers";
import { MockDreamProvider } from "../providers/MockDreamProvider";
import { hqApi } from "../providers/hq-tryon-api";
import { identityApi } from "../providers/identity-api";

afterEach(() => vi.restoreAllMocks());

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
  it("opens the local HQ workspace without creating a job or changing native generation", async () => {
    vi.spyOn(hqApi, "status").mockResolvedValue({ configured: false, authorized: false, modelReady: false });
    vi.spyOn(hqApi, "jobs").mockResolvedValue([]);
    vi.spyOn(identityApi, "profiles").mockResolvedValue([]);
    vi.spyOn(identityApi, "status").mockResolvedValue({ ready: false, modelName: "Realistic Vision", message: "未配置", loras: [] });
    const create = vi.spyOn(hqApi, "create");
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><App /></DreamProviderContext.Provider>);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "HQ 试衣" })));
    expect(screen.getByRole("heading", { level: 1, name: "HQ 试衣" })).toBeVisible();
    expect(await screen.findByText("尚未配置")).toBeVisible(); expect(create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "生成" }));
    expect(screen.getByRole("button", { name: "生成图像" })).toBeVisible();
  });
});
