import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HISTORY_POLL_INTERVAL_MS, HistoryPage } from "./HistoryPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { HistoryItem } from "../../domain/history";
import "../shell.css";
import { announceImageDeleted } from "../image-deletion";

it("removes a result deleted in another page and does not restore it from a stale refresh", async () => {
  const provider = new PagedHistoryProvider();
  render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
  await screen.findByRole("button", { name: "打开 历史项目 1" });
  act(() => announceImageDeleted("paged-history-1", provider));
  expect(screen.queryByRole("button", { name: "打开 历史项目 1" })).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "打开 历史项目 2" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新" }));
  await waitFor(() => expect(screen.getByText("历史记录已刷新")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "打开 历史项目 1" })).not.toBeInTheDocument();
});

const pagedHistoryItems: HistoryItem[] = Array.from({ length: 28 }, (_, index) => {
  const position = index + 1;
  return {
    id: `paged-history-${position}`,
    title: `历史项目 ${position}`,
    prompt: `历史提示词 ${position}`,
    negativePrompt: "",
    modelId: "model-sd15",
    modelName: "Stable Diffusion 1.5",
    width: 512,
    height: 512,
    steps: 20,
    cfg: 7,
    seed: position,
    generationTimeMs: 1200,
    createdAt: "2026-09-08T00:00:00Z",
    imageUrl: `data:image/svg+xml,history-${position}`,
    filePath: `E:\\Dream\\history\\history-${position}.png`,
    tags: [],
    favorite: false,
    status: "complete",
    truth: "observed",
  };
});

it("resets pagination after deletion in another page without skipping the shifted item", async () => {
  const provider = new DeletingPagedHistoryProvider();
  render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
  await screen.findByRole("button", { name: "打开 历史项目 24" });
  await provider.deleteHistory("paged-history-1");
  act(() => announceImageDeleted("paged-history-1", provider));
  await screen.findByRole("button", { name: "打开 历史项目 25" });
  fireEvent.click(screen.getByRole("button", { name: "加载更多历史记录" }));
  await screen.findByRole("button", { name: "打开 历史项目 28" });
  expect(screen.getAllByRole("button", { name: /^打开 历史项目 / })).toHaveLength(27);
});

class PagedHistoryProvider extends MockDreamProvider {
  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    const start = (query.page - 1) * query.pageSize;
    return {
      items: pagedHistoryItems.slice(start, start + query.pageSize),
      total: 28,
      page: query.page,
      pageSize: query.pageSize,
    };
  }
}

class DeletingPagedHistoryProvider extends MockDreamProvider {
  readonly requestedPages: number[] = [];
  private records = [...pagedHistoryItems];

  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    this.requestedPages.push(query.page);
    const start = (query.page - 1) * query.pageSize;
    return {
      items: this.records.slice(start, start + query.pageSize),
      total: this.records.length,
      page: query.page,
      pageSize: query.pageSize,
    };
  }

  override async deleteHistory(id: string) {
    this.records = this.records.filter((item) => item.id !== id);
  }
}

class EmptySecondPageProvider extends MockDreamProvider {
  readonly requestedPages: number[] = [];

  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    this.requestedPages.push(query.page);
    return {
      items: query.page === 1 ? pagedHistoryItems.slice(0, 24) : [],
      total: 28,
      page: query.page,
      pageSize: query.pageSize,
    };
  }
}

class DeferredPageOnePollProvider extends MockDreamProvider {
  private pageOneCalls = 0;
  private markPollStarted!: () => void;
  private releasePollGate!: () => void;
  readonly pollStarted = new Promise<void>((resolve) => { this.markPollStarted = resolve; });
  private readonly pollGate = new Promise<void>((resolve) => { this.releasePollGate = resolve; });

  releasePoll() {
    this.releasePollGate();
  }

  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    const page = await super.listHistory(query);
    if (query.page === 1) {
      this.pageOneCalls += 1;
      if (this.pageOneCalls === 2) {
        this.markPollStarted();
        await this.pollGate;
      }
    }
    return page;
  }
}

class NonOverlappingPollProvider extends MockDreamProvider {
  calls = 0;
  private markPollStarted!: () => void;
  private releasePollGate!: () => void;
  readonly pollStarted = new Promise<void>((resolve) => { this.markPollStarted = resolve; });
  private readonly pollGate = new Promise<void>((resolve) => { this.releasePollGate = resolve; });

  releasePoll() {
    this.releasePollGate();
  }

  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    this.calls += 1;
    if (this.calls > 1) {
      this.markPollStarted();
      await this.pollGate;
    }
    return super.listHistory(query);
  }
}

class RefreshingPagedHistoryProvider extends MockDreamProvider {
  private pageOneCalls = 0;

  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    if (query.page === 2) {
      return {
        items: pagedHistoryItems.slice(24),
        total: 28,
        page: 2,
        pageSize: query.pageSize,
      };
    }

    this.pageOneCalls += 1;
    const refreshed = this.pageOneCalls > 1;
    return {
      items: refreshed
        ? [{ ...pagedHistoryItems[0], id: "paged-history-new", title: "最新历史项目" }, ...pagedHistoryItems.slice(0, 23)]
        : pagedHistoryItems.slice(0, 24),
      total: refreshed ? 29 : 28,
      page: 1,
      pageSize: query.pageSize,
    };
  }
}

class DeferredQueryHistoryProvider extends MockDreamProvider {
  private releasePage!: () => void;
  private readonly pageReleased = new Promise<void>((resolve) => { this.releasePage = resolve; });

  releaseSecondPage() {
    this.releasePage();
  }

  override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
    const changedQuery = query.search === "仅匹配" || query.filter === "favorites";
    if (changedQuery) {
      return {
        items: [{ ...pagedHistoryItems[0], id: "filtered-history", title: "筛选后项目", favorite: true }],
        total: 1,
        page: 1,
        pageSize: query.pageSize,
      };
    }
    if (query.page === 2) {
      await this.pageReleased;
      return {
        items: pagedHistoryItems.slice(24),
        total: 28,
        page: 2,
        pageSize: query.pageSize,
      };
    }
    return {
      items: pagedHistoryItems.slice(0, 24),
      total: 28,
      page: 1,
      pageSize: query.pageSize,
    };
  }
}

describe("History page", () => {
  it("makes all 28 results reachable by loading the second history page", async () => {
    render(<DreamProviderContext.Provider value={new PagedHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);

    await screen.findByRole("heading", { name: "历史项目 1" });
    expect(screen.getAllByRole("button", { name: /打开 历史项目/ })).toHaveLength(24);
    expect(screen.getByText("1 / 28")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "加载更多历史记录" }));

    expect(await screen.findByRole("button", { name: "打开 历史项目 28" })).toBeVisible();
    expect(screen.getAllByRole("button", { name: /打开 历史项目/ })).toHaveLength(28);
    fireEvent.click(screen.getByRole("button", { name: "打开 历史项目 28" }));
    expect(screen.getByRole("heading", { name: "历史项目 28" })).toBeVisible();
    expect(screen.getByText("28 / 28")).toBeVisible();
  });

  it("reloads page 2 after deleting item 27 from a fully loaded 28-result history", async () => {
    const provider = new DeletingPagedHistoryProvider();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "历史项目 1" });
    fireEvent.click(screen.getByRole("button", { name: "加载更多历史记录" }));
    await screen.findByRole("button", { name: "打开 历史项目 28" });
    fireEvent.click(screen.getByRole("button", { name: "打开 历史项目 27" }));
    fireEvent.click(screen.getByRole("button", { name: "删除结果" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "打开 历史项目 27" })).not.toBeInTheDocument());

    fireEvent.click(await screen.findByRole("button", { name: "加载更多历史记录" }));

    await waitFor(() => expect(provider.requestedPages.filter((page) => page === 2)).toHaveLength(2));
    expect(provider.requestedPages.at(-1)).toBe(2);
    for (const position of [25, 26, 28]) {
      expect(await screen.findByRole("button", { name: `打开 历史项目 ${position}` })).toBeVisible();
    }
  });

  it("stops pagination when the provider returns an empty next page", async () => {
    const provider = new EmptySecondPageProvider();
    render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "历史项目 1" });

    fireEvent.click(screen.getByRole("button", { name: "加载更多历史记录" }));

    expect(await screen.findByRole("status")).toHaveTextContent("没有更多历史记录");
    expect(screen.queryByRole("button", { name: "加载更多历史记录" })).not.toBeInTheDocument();
    expect(provider.requestedPages).toEqual([1, 2]);
  });

  it("reconciles a refreshed first page without duplicate ids or selection drift", async () => {
    vi.useFakeTimers();
    try {
      render(<DreamProviderContext.Provider value={new RefreshingPagedHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);
      await act(async () => { for (let index = 0; index < 3; index += 1) await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "加载更多历史记录" }));
      await act(async () => { for (let index = 0; index < 3; index += 1) await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: "打开 历史项目 27" }));
      expect(screen.getByText("27 / 28")).toBeVisible();

      await act(async () => {
        vi.advanceTimersByTime(HISTORY_POLL_INTERVAL_MS + 200);
        for (let index = 0; index < 5; index += 1) await Promise.resolve();
      });

      expect(screen.getAllByRole("button", { name: /打开 (?:最新历史项目|历史项目)/ })).toHaveLength(29);
      expect(screen.getAllByRole("button", { name: "打开 历史项目 1" })).toHaveLength(1);
      expect(screen.getByRole("heading", { name: "历史项目 27" })).toBeVisible();
      expect(screen.getByText("28 / 29")).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the latest user selection when a deferred page-1 poll completes", async () => {
    vi.useFakeTimers();
    try {
      const provider = new DeferredPageOnePollProvider();
      render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
      await act(async () => { for (let index = 0; index < 3; index += 1) await Promise.resolve(); });
      expect(screen.getByRole("heading", { name: "a serene mountain lake at sunrise" })).toBeVisible();
      await act(async () => { vi.advanceTimersByTime(HISTORY_POLL_INTERVAL_MS); await provider.pollStarted; });

      fireEvent.click(screen.getByRole("button", { name: /打开 dramatic studio portrait/i }));
      expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();

      await act(async () => {
        provider.releasePoll();
        for (let index = 0; index < 5; index += 1) await Promise.resolve();
      });

      expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
      expect(screen.getByText("2 / 9")).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not overlap interval refreshes while a history request is still running", async () => {
    vi.useFakeTimers();
    try {
      const provider = new NonOverlappingPollProvider();
      render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
      await act(async () => { for (let index = 0; index < 3; index += 1) await Promise.resolve(); });
      await act(async () => { vi.advanceTimersByTime(HISTORY_POLL_INTERVAL_MS); await provider.pollStarted; });

      await act(async () => { vi.advanceTimersByTime(HISTORY_POLL_INTERVAL_MS * 3); });

      expect(provider.calls).toBe(2);
      provider.releasePoll();
      await act(async () => { for (let index = 0; index < 3; index += 1) await Promise.resolve(); });
    } finally {
      vi.useRealTimers();
    }
  });

  it("styles the history workstation as a responsive main-viewer grid", async () => {
    const { container } = render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });
    const workstation = container.querySelector<HTMLElement>(".history-workstation");
    expect(workstation).not.toBeNull();
    if (!workstation) throw new Error("history workstation is missing");

    const desktopStyle = window.getComputedStyle(workstation);
    expect(desktopStyle.display).toBe("grid");
    expect(desktopStyle.gridTemplateColumns).toBe("minmax(0, 1.3fr) minmax(330px, .7fr)");

    const loadedCss = Array.from(document.styleSheets)
      .flatMap((sheet) => Array.from(sheet.cssRules))
      .map((rule) => rule.cssText)
      .join("\n");
    expect(loadedCss).toMatch(
      /@media \(max-width:\s*850px\)\s*\{[^@]*?\.history-workstation\s*\{[^}]*grid-template-columns:\s*1fr;/s,
    );
  });

  it.each([
    ["搜索", () => fireEvent.change(screen.getByRole("textbox", { name: "搜索历史记录" }), { target: { value: "仅匹配" } })],
    ["筛选", () => fireEvent.click(screen.getByRole("button", { name: "收藏" }))],
  ])("resets pagination when %s changes while the previous page is pending", async (_label, changeQuery) => {
    const provider = new DeferredQueryHistoryProvider();
    render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "历史项目 1" });
    fireEvent.click(screen.getByRole("button", { name: "加载更多历史记录" }));

    changeQuery();
    expect(await screen.findByRole("heading", { name: "筛选后项目" })).toBeVisible();
    await act(async () => { provider.releaseSecondPage(); await Promise.resolve(); });

    await waitFor(() => expect(screen.getAllByRole("button", { name: /打开/ })).toHaveLength(1));
    expect(screen.queryByRole("button", { name: "打开 历史项目 25" })).not.toBeInTheDocument();
    expect(screen.getByText("1 / 1")).toBeVisible();
  });

  it("keeps viewer context while navigating and deleting a result", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    const first = await screen.findByRole("button", { name: /打开 a serene mountain lake at sunrise/i });
    expect(first).toBeVisible();
    expect(screen.getByRole("button", { name: "全部（9）" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "a serene mountain lake at sunrise" })).toBeVisible();

    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "上一个结果" }));
    expect(screen.getByRole("heading", { name: "a serene mountain lake at sunrise" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "删除结果" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("button", { name: /打开 a serene mountain lake at sunrise/i })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
  });

  it("keeps a result when deletion is cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });

    fireEvent.click(screen.getByRole("button", { name: "删除结果" }));

    expect(confirm).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /打开 a serene mountain lake at sunrise/i })).toBeInTheDocument();
  });

  it("does not consume viewer shortcuts while the search field is focused", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    const search = await screen.findByRole("textbox", { name: "搜索历史记录" });
    const first = screen.getByRole("heading", { name: "a serene mountain lake at sunrise" });

    search.focus();
    fireEvent.keyDown(search, { key: "ArrowRight" });
    fireEvent.keyDown(search, { key: "Delete" });

    expect(first).toBeVisible();
    expect(screen.getByRole("button", { name: /打开 a serene mountain lake at sunrise/i })).toBeInTheDocument();
  });

  it("clears the viewer when Escape is pressed outside an editable control", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByText("选择一个结果查看详情。")).toBeVisible();
  });

  it("renders an explicit empty state when history has no matches", async () => {
    const provider = new MockDreamProvider();
    render(<DreamProviderContext.Provider value={provider}><HistoryPage /></DreamProviderContext.Provider>);
    const search = await screen.findByRole("textbox", { name: "搜索历史记录" });

    fireEvent.change(search, { target: { value: "no-result-will-match" } });

    expect(await screen.findByText("没有符合条件的历史记录。")).toBeVisible();
  });

  it("marks history items created with unsafe quality parameters", async () => {
    class LowQualityHistoryProvider extends MockDreamProvider {
      override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
        const page = await super.listHistory(query);
        return { ...page, items: page.items.map((item, index) => index === 0 ? { ...item, width: 256, height: 256, steps: 2 } : item) };
      }
    }

    render(<DreamProviderContext.Provider value={new LowQualityHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);

    expect(await screen.findByText("质量风险")).toBeVisible();
  });

  it("does not flag a distilled model at its registered low-step profile", async () => {
    class DistilledHistoryProvider extends MockDreamProvider {
      override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
        const page = await super.listHistory(query);
        return {
          ...page,
          items: page.items.slice(0, 1).map((item) => ({
            ...item,
            width: 768,
            height: 768,
            steps: 4,
            generationDefaults: {
              width: 768,
              height: 768,
              steps: 4,
              cfg: 2,
              samplingMethod: "dpm++2m" as const,
              scheduler: "discrete" as const,
            },
          })),
          total: 1,
        };
      }
    }

    render(<DreamProviderContext.Provider value={new DistilledHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);

    await screen.findByRole("button", { name: "全部（1）" });
    expect(screen.queryByText("质量风险")).not.toBeInTheDocument();
  });

  it("uses the registered eight-step profile in warnings instead of recommending twenty steps", async () => {
    class LightningHistoryProvider extends MockDreamProvider {
      override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
        const page = await super.listHistory(query);
        return { ...page, total: 1, items: page.items.slice(0, 1).map(item => ({ ...item,
          width: 768, height: 768, steps: 6,
          generationDefaults: { width: 768, height: 768, steps: 8, cfg: 2, samplingMethod: "dpm++2m_sde" as const, scheduler: "karras" as const },
        })) };
      }
    }
    render(<DreamProviderContext.Provider value={new LightningHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    const warning = await screen.findByText("质量风险");
    expect(warning.getAttribute("title")).toContain("、8 步");
    expect(warning.getAttribute("title")).not.toContain("标准 SDXL");
  });

  it("lazy loads history thumbnails to reduce renderer image pressure", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });

    const thumbnails = Array.from(document.querySelectorAll<HTMLImageElement>(".history-card img"));
    expect(thumbnails.length).toBeGreaterThan(0);
    expect(thumbnails.every((image) => image.getAttribute("loading") === "lazy")).toBe(true);
    expect(thumbnails.every((image) => image.getAttribute("decoding") === "async")).toBe(true);
    expect(document.querySelector<HTMLImageElement>(".viewer-image")?.getAttribute("decoding")).toBe("async");
  });

  it("renders an explicit history error when the provider fails", async () => {
    class ErrorHistoryProvider extends MockDreamProvider {
      override async listHistory(): Promise<never> { throw new Error("History unavailable"); }
    }

    render(<DreamProviderContext.Provider value={new ErrorHistoryProvider()}><HistoryPage /></DreamProviderContext.Provider>);

    expect(await screen.findByRole("alert")).toHaveTextContent("History unavailable");
  });

  it("shows carousel position and supports zoom without changing the selected image", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });

    expect(screen.getByText("1 / 9")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "放大预览" }));
    expect(screen.getByText("缩放 1.2×")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "下一个结果" }));
    expect(screen.getByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
  });

  it("moves to the next image with a horizontal pointer swipe", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });
    const stage = document.querySelector<HTMLElement>(".history-viewer-stage");
    expect(stage).not.toBeNull();
    if (!stage) throw new Error("history viewer stage is missing");
    fireEvent.pointerDown(stage, { clientX: 240, clientY: 120, pointerId: 1 });
    fireEvent.pointerUp(stage, { clientX: 80, clientY: 120, pointerId: 1 });

    expect(await screen.findByRole("heading", { name: "dramatic studio portrait" })).toBeVisible();
  });

  it("opens a two-image comparison and offers a rerun action", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><HistoryPage /></DreamProviderContext.Provider>);
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });

    fireEvent.click(screen.getByRole("button", { name: "比较当前两张" }));
    expect(await screen.findByText("并排比较")).toBeVisible();
    expect(screen.getAllByRole("img", { name: /比较图/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "重新生成此图" })).toBeVisible();
  });

  it("refreshes the current history list and keeps the selected item when it still exists", async () => {
    vi.useFakeTimers();
    try {
      class RefreshingProvider extends MockDreamProvider {
        private calls = 0;
        override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
          const page = await super.listHistory(query);
          this.calls += 1;
          if (this.calls > 1) {
            return { ...page, items: [{ ...page.items[0], id: "newest-job", title: "最新任务" }, ...page.items.slice(1)] };
          }
          return page;
        }
      }
      render(<DreamProviderContext.Provider value={new RefreshingProvider()}><HistoryPage /></DreamProviderContext.Provider>);
      await act(async () => { await Promise.resolve(); });
      await act(async () => { vi.advanceTimersByTime(HISTORY_POLL_INTERVAL_MS + 200); for (let index = 0; index < 5; index += 1) await Promise.resolve(); });
      expect(screen.getByRole("button", { name: /打开 最新任务/ })).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });
});
