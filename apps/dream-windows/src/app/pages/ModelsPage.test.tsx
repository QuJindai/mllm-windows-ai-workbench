import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelsPage } from "./ModelsPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";

describe("Models page", () => {
  it("lists verified E-drive models and opens an inspector", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><ModelsPage /></DreamProviderContext.Provider>);
    const model = await screen.findByRole("button", { name: /打开 CyberRealistic XL v10（标准版）/i });
    expect(screen.getByText("已验证")).toBeVisible();
    expect(screen.getByText("SDXL")).toBeVisible();
    fireEvent.click(model);
    expect(screen.getByRole("heading", { name: "模型详情" })).toBeVisible();
    expect(screen.getByText(/E:\\Dream\\models\\windows\\gguf/)).toBeVisible();
  });

  it("opens the E-drive model folder instead of presenting an inert import action", async () => {
    class OpenModelsProvider extends MockDreamProvider {
      openedEntry: string | null = null;
      override async openWorkspace(entry: "models") {
        this.openedEntry = entry;
        return { opened: true, entry, path: "E:\\Dream\\models" };
      }
    }
    const provider = new OpenModelsProvider();
    render(<DreamProviderContext.Provider value={provider}><ModelsPage /></DreamProviderContext.Provider>);

    fireEvent.click(await screen.findByRole("button", { name: "打开模型目录" }));

    await waitFor(() => expect(provider.openedEntry).toBe("models"));
    expect(screen.getByRole("status")).toHaveTextContent("已打开 E:\\Dream\\models");
    expect(screen.queryByRole("button", { name: "导入" })).not.toBeInTheDocument();
  });

  it("renders an explicit empty state when the registry has no models", async () => {
    class EmptyModelsProvider extends MockDreamProvider {
      override async listModels() { return []; }
    }

    render(<DreamProviderContext.Provider value={new EmptyModelsProvider()}><ModelsPage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("heading", { name: "未找到模型" })).toBeVisible();
    expect(screen.getByRole("button", { name: "打开模型目录" })).toBeVisible();
    expect(screen.getByRole("button", { name: "重新扫描" })).toBeVisible();
  });

  it("renders an explicit registry error when the provider fails", async () => {
    class ErrorModelsProvider extends MockDreamProvider {
      override async listModels(): Promise<never> { throw new Error("Model registry unavailable"); }
    }

    render(<DreamProviderContext.Provider value={new ErrorModelsProvider()}><ModelsPage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("alert")).toHaveTextContent("Model registry unavailable");
  });
});
