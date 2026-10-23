import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { WorkspaceEntry } from "../../domain/settings";
import { UI_PREFERENCES_KEY } from "../ui-preferences";
import { DreamHttpProvider } from "../../providers/DreamHttpProvider";

const hardware: HardwareSnapshot = {
  gpuName: "Test GPU",
  vramTotalMiB: 6144,
  vramUsedMiB: 0,
  gpuUtil: 0,
  ramTotalBytes: 64 * 1024 ** 3,
  ramUsedBytes: 0,
  cudaReady: true,
  dreamRoot: "E:\\Dream",
  truth: "observed",
  isMock: false,
  cpuName: "Test CPU",
  cpuCores: 8,
  cpuThreads: 16,
};

describe("Settings page", () => {
  it("shows independent research readiness from capabilities and refreshes without changing capture settings", async () => {
    const settings = await new MockDreamProvider().getSettings();
    const caps = {
      conditioning_influence: { available: true, truth: "observed" },
      self_attention: { available: true, truth: "observed" },
      attention: { available: false, truth: "unavailable" },
    };
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url === "/api/settings" ? settings : caps)));
    vi.stubGlobal("fetch", fetcher);
    try {
      render(<DreamProviderContext.Provider value={new DreamHttpProvider()}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
      fireEvent.click(await screen.findByRole("tab", { name: "高级" }));
      const research = await screen.findByRole("region", { name: "研究采集" });
      await waitFor(() => expect(within(research).getByText("H6 条件影响").closest("tr")).toHaveTextContent("采集已就绪"));
      expect(within(research).getByText("H7 自注意力").closest("tr")).toHaveTextContent("采集已就绪");
      expect(within(research).getByText("H7 交叉注意力").closest("tr")).toHaveTextContent("不可用");
      expect(research).toHaveTextContent("能力就绪不代表每条历史记录都已采集");
      caps.self_attention.available = false;
      caps.self_attention.truth = "unavailable";
      fireEvent.click(within(research).getByRole("button", { name: "刷新采集能力" }));
      await waitFor(() => expect(within(research).getByText("H7 自注意力").closest("tr")).toHaveTextContent("不可用"));
      expect(fetcher.mock.calls.every(([url]) => url === "/api/settings" || url === "/api/capabilities" || url === "/api/operations")).toBe(true);
    } finally { vi.unstubAllGlobals(); }
  });

  it("keeps legacy and failed capability responses unconfirmed instead of claiming missing engine support", async () => {
    const getCapabilities = vi.fn().mockResolvedValue({ attention: { available: true, truth: "observed" } });
    const provider = Object.assign(new MockDreamProvider(), { getCapabilities });
    render(<DreamProviderContext.Provider value={provider}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
    fireEvent.click(await screen.findByRole("tab", { name: "高级" }));
    const research = await screen.findByRole("region", { name: "研究采集" });
    await waitFor(() => expect(within(research).getByText("H7 交叉注意力").closest("tr")).toHaveTextContent("采集已就绪"));
    expect(within(research).getByText("H6 条件影响").closest("tr")).toHaveTextContent("未确认");
    expect(within(research).getByText("H7 自注意力").closest("tr")).toHaveTextContent("未确认");
    getCapabilities.mockRejectedValueOnce(new Error("network failed"));
    fireEvent.click(within(research).getByRole("button", { name: "刷新采集能力" }));
    expect(await within(research).findByText(/研究采集能力读取失败/)).toBeVisible();
    expect(within(research).queryByText("采集已就绪")).not.toBeInTheDocument();
  });

  it("persists interface preferences and never labels unmeasured checks healthy", async () => {
    const provider = new MockDreamProvider();
    const first = render(<DreamProviderContext.Provider value={provider}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
    await screen.findByRole("tabpanel");
    expect(screen.queryByText("✓ 系统健康")).not.toBeInTheDocument();
    expect(screen.getAllByText("未独立检测").length).toBe(2);
    fireEvent.click(screen.getByRole("tab", { name: "用户界面" }));
    fireEvent.change(screen.getByRole("combobox", { name: "文字大小" }), { target: { value: "large" } });
    first.unmount();
    render(<DreamProviderContext.Provider value={provider}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
    await screen.findByRole("tabpanel");
    fireEvent.click(screen.getByRole("tab", { name: "用户界面" }));
    expect(screen.getByRole("combobox", { name: "文字大小" })).toHaveValue("large");
    fireEvent.click(screen.getByRole("tab", { name: "高级" }));
    const panel = screen.getByRole("tabpanel", { name: "高级" });
    fireEvent.change(within(panel).getByRole("combobox", { name: "自动刷新" }), { target: { value: "off" } });
    expect(within(panel).getByRole("combobox", { name: "刷新间隔" })).toBeDisabled();
    await waitFor(() => expect(within(panel).getByRole("button", { name: "刷新采集能力" })).toBeEnabled());
    localStorage.removeItem(UI_PREFERENCES_KEY);
  });
  it("switches between real tab panels", async () => {
    render(<DreamProviderContext.Provider value={new MockDreamProvider()}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
    await screen.findByRole("tabpanel");

    fireEvent.click(screen.getByRole("tab", { name: "模型与推理" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("推理与内存设置");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("模型加载与采样策略");

    fireEvent.click(screen.getByRole("tab", { name: "关于" }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent("Dream Windows 浏览器工作站");
  });

  it("uses a fixed workspace key for opening directories", async () => {
    const openWorkspace = vi.fn(async (entry: WorkspaceEntry) => ({ entry, path: "E:\\Dream" }));
    const provider = Object.assign(new MockDreamProvider(), { openWorkspace });
    render(<DreamProviderContext.Provider value={provider}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
    await screen.findByRole("tabpanel");

    fireEvent.click(screen.getByRole("button", { name: "打开模型" }));

    await waitFor(() => expect(openWorkspace).toHaveBeenCalledWith("models"));
    expect(screen.getByRole("status")).toHaveTextContent("模型");
  });

  it("exposes settings export as a browser download and rebuilds the model index", async () => {
    const reindexModels = vi.fn(async () => [{ id: "model" }]);
    const provider = Object.assign(new MockDreamProvider(), { reindexModels });
    render(<DreamProviderContext.Provider value={provider}><SettingsPage hardware={hardware} /></DreamProviderContext.Provider>);
    await screen.findByRole("tabpanel");

    const exportLink = screen.getByRole("link", { name: /导出配置/ });
    expect(exportLink).toHaveAttribute("href", "/api/settings/export");
    expect(exportLink).toHaveAttribute("download", "dream-settings.json");

    fireEvent.click(screen.getByRole("button", { name: /重建索引/ }));
    await waitFor(() => expect(reindexModels).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("status")).toHaveTextContent("模型索引已刷新");
  });
});
