import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelsPage } from "./ModelsPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";

describe("Models page", () => {
  it("keeps the inspector and verify action on a visible search result", async () => {
    class SearchModelsProvider extends MockDreamProvider {
      verifiedId: string | null = null;
      override async listModels() {
        const models = await super.listModels();
        return [...models, { ...models[0], id: "lightning", displayName: "DreamShaper Lightning" }];
      }
      override async verifyModel(id: string) {
        this.verifiedId = id;
        return (await this.listModels()).find(model => model.id === id)!;
      }
    }
    const provider = new SearchModelsProvider();
    render(<DreamProviderContext.Provider value={provider}><ModelsPage /></DreamProviderContext.Provider>);
    await screen.findByRole("button", { name: /打开 DreamShaper Lightning/ });
    fireEvent.change(screen.getByRole("textbox", { name: "搜索模型" }), { target: { value: "DreamShaper" } });
    expect(within(screen.getByRole("complementary")).getByText("DreamShaper Lightning")).toBeVisible();
    expect(screen.getByRole("button", { name: /打开 DreamShaper Lightning/ })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "验证 SHA" }));
    await waitFor(() => expect(provider.verifiedId).toBe("lightning"));
  });

  it("hides stale inspector actions when the category or search has no matches", async () => {
    class CheckpointsProvider extends MockDreamProvider {
      override async listModels() { return (await super.listModels()).filter(model => model.kind === "Checkpoint"); }
    }
    render(<DreamProviderContext.Provider value={new CheckpointsProvider()}><ModelsPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "模型详情" });
    fireEvent.click(screen.getByRole("button", { name: "LoRA" }));
    expect(screen.getByText("没有符合筛选条件的模型。")).toBeVisible();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "验证 SHA" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    expect(screen.getByRole("heading", { name: "模型详情" })).toBeVisible();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索模型" }), { target: { value: "nonexistent-model" } });
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

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
