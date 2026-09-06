import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelsPage } from "./ModelsPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";

describe("Models page", () => {
  it("lists verified E-drive models and opens an inspector", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><ModelsPage /></DreamProviderContext.Provider>);
    const model = await screen.findByRole("button", { name: /CyberRealistic v10 DMD2/i });
    expect(screen.getByText("VERIFIED")).toBeVisible();
    expect(screen.getByText("SDXL")).toBeVisible();
    fireEvent.click(model);
    expect(screen.getByRole("heading", { name: "Model details" })).toBeVisible();
    expect(screen.getByText(/E:\\Dream\\models\\windows\\gguf/)).toBeVisible();
  });

  it("renders an explicit empty state when the registry has no models", async () => {
    class EmptyModelsProvider extends MockDreamProvider {
      override async listModels() { return []; }
    }

    render(<DreamProviderContext.Provider value={new EmptyModelsProvider()}><ModelsPage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("heading", { name: "No models found" })).toBeVisible();
  });

  it("renders an explicit registry error when the provider fails", async () => {
    class ErrorModelsProvider extends MockDreamProvider {
      override async listModels(): Promise<never> { throw new Error("Model registry unavailable"); }
    }

    render(<DreamProviderContext.Provider value={new ErrorModelsProvider()}><ModelsPage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("alert")).toHaveTextContent("Model registry unavailable");
  });
});
