import { render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { DreamProviderContext } from "./providers";
import { MockDreamProvider } from "../providers/MockDreamProvider";

describe("Dream app shell", () => {
  it("shows the six primary navigation entries and mock hardware status", async () => {
    render(
      <DreamProviderContext.Provider value={new MockDreamProvider()}>
        <App />
      </DreamProviderContext.Provider>,
    );

    await waitFor(() => expect(screen.getByText("Hardware Status")).toBeVisible());
    expect(screen.getByRole("heading", { name: "Generate" })).toBeVisible();
    for (const label of ["Generate", "Models", "History", "Lab", "Microscope", "Settings"]) {
      expect(screen.getByRole("button", { name: label })).toBeVisible();
    }
    expect(screen.getByText("DEMO / MOCK")).toBeVisible();
  });
});
