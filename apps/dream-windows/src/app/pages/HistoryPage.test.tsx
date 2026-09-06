import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HistoryPage } from "./HistoryPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";

describe("History page", () => {
  it("keeps viewer context while navigating and deleting a result", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    const first = await screen.findByRole("button", { name: /Open a serene mountain lake at sunrise/i });
    expect(first).toBeVisible();
    expect(screen.getByRole("heading", { name: "a serene mountain lake at sunrise" })).toBeVisible();

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Previous result" }));
    expect(screen.getByRole("heading", { name: "a serene mountain lake at sunrise" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Delete result" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: /Open a serene mountain lake at sunrise/i })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
  });
});
