import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { HardwareSnapshot } from "../../domain/hardware";
import type { WorkspaceEntry } from "../../domain/settings";

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
