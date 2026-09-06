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

  it("does not consume viewer shortcuts while the search field is focused", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    const search = await screen.findByRole("textbox", { name: "Search history" });
    const first = screen.getByRole("heading", { name: "a serene mountain lake at sunrise" });

    search.focus();
    fireEvent.keyDown(search, { key: "ArrowRight" });
    fireEvent.keyDown(search, { key: "Delete" });

    expect(first).toBeVisible();
    expect(screen.getByRole("button", { name: /Open a serene mountain lake at sunrise/i })).toBeInTheDocument();
  });

  it("clears the viewer when Escape is pressed outside an editable control", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByText("Select a result to inspect it.")).toBeVisible();
  });

  it("renders an explicit empty state when history has no matches", async () => {
    const provider = new MockDreamProvider();
    render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
    const search = await screen.findByRole("textbox", { name: "Search history" });

    fireEvent.change(search, { target: { value: "no-result-will-match" } });

    expect(await screen.findByText("No history matches this query.")).toBeVisible();
  });

  it("renders an explicit history error when the provider fails", async () => {
    class ErrorHistoryProvider extends MockDreamProvider {
      override async listHistory(): Promise<never> { throw new Error("History unavailable"); }
    }

    render(<DreamProviderContext.Provider value={new ErrorHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("alert")).toHaveTextContent("History unavailable");
  });
});
