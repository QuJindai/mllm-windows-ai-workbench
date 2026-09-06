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
});
