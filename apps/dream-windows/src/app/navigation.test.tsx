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

    await waitFor(() => expect(screen.getByText("DEMO / MOCK")).toBeInTheDocument());
    for (const [label, heading] of [
      ["Generate", "Generate"],
      ["Models", "Models"],
      ["History", "History"],
      ["Lab", "Semantic Lab"],
      ["Microscope", "Microscope"],
      ["Settings", "Settings"],
    ]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
      expect(screen.getByRole("heading", { name: heading, level: 1 })).toBeInTheDocument();
    }
  });
});
