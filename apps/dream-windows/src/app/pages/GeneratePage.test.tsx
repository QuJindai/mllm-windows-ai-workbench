import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GeneratePage } from "./GeneratePage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import hardwareFixture from "../../fixtures/hardware.json";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { GenerationJob } from "../../domain/generation";

describe("Generate page", () => {
  it("submits a typed request and renders the mock result lifecycle", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    const submit = await screen.findByRole("button", { name: "Generate image" });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    expect(await screen.findByRole("progressbar", { name: "Generation progress" })).toBeVisible();
    await waitFor(() => expect(screen.getAllByText("Complete").length).toBeGreaterThan(0), { timeout: 1800 });
    expect(screen.getByAltText("Mock generated result")).toBeVisible();
  });

  it("disables submission when the prompt is empty", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    const prompt = await screen.findByLabelText("Prompt");
    fireEvent.change(prompt, { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Generate image" })).toBeDisabled();
  });

  it("disables generation and explains when CUDA is unavailable", async () => {
    const hardware: HardwareSnapshot = { ...(hardwareFixture as HardwareSnapshot), cudaReady: false, truth: "unavailable" };
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><GeneratePage hardware={hardware} /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("button", { name: "Generate image" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("CUDA unavailable");
  });

  it("renders a provider error when a generation job fails", async () => {
    class FailingProvider extends MockDreamProvider {
      override async getJob(id: string): Promise<GenerationJob> {
        const job = await super.getJob(id);
        return { ...job, state: "failed", progress: 0, message: "Generation failed", error: "CUDA kernel unavailable" };
      }
    }

    render(<DreamProviderContext.Provider value={new FailingProvider()}><GeneratePage /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("button", { name: "Generate image" }));

    expect(await screen.findByText("CUDA kernel unavailable")).toBeVisible();
  });
});
