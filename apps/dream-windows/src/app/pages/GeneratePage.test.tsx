import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GeneratePage } from "./GeneratePage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";

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
});
