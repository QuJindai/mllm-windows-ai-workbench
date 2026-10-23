import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { DreamProviderContext } from "./providers";
import { DreamHttpProvider } from "../providers/DreamHttpProvider";
import { MockDreamProvider } from "../providers/MockDreamProvider";
import { TopBar } from "./components/TopBar";
import { MicroscopePage } from "./pages/MicroscopePage";
import type { HardwareSnapshot } from "../domain/hardware";

const sample = (gpuUtil = 80) => ({
  gpuName: "NVIDIA RTX 1000 Ada Generation Laptop GPU", gpuUtil,
  vramTotalMiB: 6141, vramUsedMiB: 1506, gpuTempC: 57, gpuPowerW: 32.5,
  ramTotalBytes: 64 * 1024 ** 3, ramUsedBytes: 16 * 1024 ** 3,
  cudaReady: true, dreamRoot: "E:\\Dream", truth: "observed" as const, isMock: false,
  backend: "stable-diffusion.cpp + CUDA", backendTruth: "derived", cpuName: "CPU",
  cpuCores: 20, cpuThreads: 28, driverVersion: "595.95", eDriveTotalBytes: 100000, eDriveFreeBytes: 50000,
  sampledAt: new Date().toISOString(), telemetrySource: "nvidia-smi + psutil",
});
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const header = () => within(screen.getByRole("banner"));
const advance = async (ms: number) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };

function network(read: (init: RequestInit) => Promise<Response>) {
  const requests: RequestInit[] = [];
  vi.stubGlobal("fetch", vi.fn((path: string, init: RequestInit) => {
    if (path === "/api/hardware") { requests.push(init); return read(init); }
    if (path === "/api/models") return Promise.resolve(response([]));
    throw new Error(`Unexpected request: ${path}`);
  }));
  return requests;
}

async function mount(provider = new DreamHttpProvider()) {
  let view!: ReturnType<typeof render>;
  await act(async () => { view = render(<DreamProviderContext.Provider value={provider}><App /></DreamProviderContext.Provider>); });
  return view;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-11T08:00:00Z"));
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("GUI-02 hardware acquisition to shell", () => {
  it("refreshes readings, bars and acquisition time through the full HTTP provider", async () => {
    let utilization = 80;
    const requests = network(async () => response(sample(utilization)));
    await mount();
    expect(header().getByText("80%")).toBeVisible();
    expect(header().getByText(/1506.*6141 MiB/)).toBeVisible();
    const gpu = header().getByRole("meter", { name: "GPU 使用率" });
    expect(gpu).toHaveAttribute("aria-valuenow", "80");
    expect(gpu.firstElementChild).toHaveStyle({ width: "80%" });
    expect(header().getByRole("meter", { name: "RAM 使用率" }).firstElementChild).toHaveStyle({ width: "25%" });
    expect(screen.getByRole("banner").querySelector("time")).toHaveAttribute("datetime", "2026-10-11T08:00:00.000Z");
    utilization = 12;
    await advance(3000);
    expect(header().getByText("12%")).toBeVisible();
    expect(gpu.firstElementChild).toHaveStyle({ width: "12%" });
    expect(screen.getByRole("banner").querySelector("time")).toHaveAttribute("datetime", "2026-10-11T08:00:03.000Z");
    expect(requests).toHaveLength(2);
    expect(requests[0].cache).toBe("no-store");
  });

  it("clears failed readings and recovers on a later poll without fake zeroes", async () => {
    let failed = false;
    network(async () => failed ? response({ code: "HARDWARE_TELEMETRY_UNAVAILABLE", message: "硬件读取失败" }, 503) : response(sample()));
    await mount();
    failed = true;
    await advance(3000);
    expect(header().queryByText("80%")).not.toBeInTheDocument();
    expect(header().queryByText("0%")).not.toBeInTheDocument();
    expect(header().getByText("硬件不可用")).toBeVisible();
    expect(header().getByRole("meter", { name: "GPU 使用率" })).not.toHaveAttribute("aria-valuenow");
    expect(screen.getByRole("button", { name: "生成图像" })).toBeDisabled();
    failed = false;
    await advance(3000);
    expect(header().getByText("80%")).toBeVisible();
  });

  it("bounds a hanging request, prevents overlap and ignores its late result", async () => {
    let complete!: (value: Response) => void;
    const requests = network(() => new Promise((resolve) => { complete = resolve; }));
    await mount();
    await advance(12000);
    expect(requests).toHaveLength(1);
    expect(requests[0].signal?.aborted).toBe(true);
    expect(header().getByText("硬件不可用")).toBeVisible();
    await act(async () => { complete(response(sample(99))); });
    expect(header().queryByText("99%")).not.toBeInTheDocument();
  });

  it("pauses hidden tabs and immediately refreshes on return", async () => {
    const requests = network(async () => response(sample()));
    await mount();
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    await advance(60000);
    expect(requests).toHaveLength(1);
    expect(header().queryByText("80%")).not.toBeInTheDocument();
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    await act(async () => { fireEvent(document, new Event("visibilitychange")); });
    expect(requests).toHaveLength(2);
    expect(header().getByText("80%")).toBeVisible();
  });

  it("aborts an in-flight request on unmount and leaves no polling timer", async () => {
    const requests = network(() => new Promise(() => {}));
    const view = await mount();
    view.unmount();
    expect(requests[0].signal?.aborted).toBe(true);
    await advance(30000);
    expect(requests).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([undefined, "not-a-date", "2026-10-11T07:59:00Z"])("rejects missing or stale acquisition time (%s)", async (sampledAt) => {
    network(async () => response({ ...sample(), sampledAt }));
    await mount();
    expect(header().queryByText("80%")).not.toBeInTheDocument();
    expect(header().getByText("硬件不可用")).toBeVisible();
  });

  it("keeps a real idle zero and demo data distinguishable", async () => {
    network(async () => response(sample(0)));
    const view = await mount();
    expect(header().getByText("0%")).toBeVisible();
    expect(header().getByRole("meter", { name: "GPU 使用率" })).toHaveAttribute("aria-valuenow", "0");
    await act(async () => { view.rerender(<DreamProviderContext.Provider value={new MockDreamProvider()}><App /></DreamProviderContext.Provider>); });
    expect(header().getByText("演示 / 模拟")).toBeVisible();
    expect(header().queryByText("采样 / 后端")).not.toBeInTheDocument();
  });

  it("does not label loading as observed or render invalid percentages", () => {
    const view = render(<TopBar hardware={null} loading error={null} mode="backend" />);
    expect(header().queryByText("实时 / 后端")).not.toBeInTheDocument();
    const invalid: HardwareSnapshot = { ...sample(), gpuUtil: Number.NaN, ramTotalBytes: 0 };
    view.rerender(<TopBar hardware={invalid} loading={false} error={null} mode="backend" />);
    expect(header().queryByText(/NaN|Infinity/)).not.toBeInTheDocument();
    expect(header().getByRole("meter", { name: "GPU 使用率" })).not.toHaveAttribute("aria-valuenow");
  });

  it("retries after an abort-aware network timeout and recovers", async () => {
    let blocked = true;
    const requests = network((init) => blocked ? new Promise((_, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }) : Promise.resolve(response(sample(35))));
    await mount();
    await advance(4000);
    expect(header().getByText("硬件不可用")).toBeVisible();
    blocked = false;
    await advance(3000);
    expect(requests).toHaveLength(2);
    expect(header().getByText("35%")).toBeVisible();
  });

  it("does not keep cached telemetry fresh just because HTTP succeeds", async () => {
    const cached = sample();
    network(async () => response(cached));
    await mount();
    await advance(10000);
    expect(header().queryByText("80%")).not.toBeInTheDocument();
    expect(header().getByText("硬件不可用")).toBeVisible();
  });

  it.each([true, false])("keeps the complete getHardware schema compatible with Microscope (available=%s)", async (available) => {
    network(async () => available ? response(sample()) : response({ code: "HARDWARE_TELEMETRY_UNAVAILABLE", message: "硬件不可用" }, 503));
    const provider = new MockDreamProvider();
    provider.getHardware = () => new DreamHttpProvider().getHardware();
    await act(async () => { render(<DreamProviderContext.Provider value={provider}><MicroscopePage /></DreamProviderContext.Provider>); });
    const evidence = screen.getByText("当前硬件快照").closest(".surface-card") as HTMLElement;
    if (available) {
      expect(within(evidence).getByText("1,506 / 6,141 MiB")).toBeVisible();
      expect(within(evidence).getByText("16.0 / 64.0 GiB")).toBeVisible();
      expect(within(evidence).getByText("57 °C")).toBeVisible();
      expect(within(evidence).getByText("stable-diffusion.cpp + CUDA")).toBeVisible();
    } else {
      expect(within(evidence).getAllByText("—")).toHaveLength(4);
      expect(within(evidence).queryByText("0")).not.toBeInTheDocument();
    }
  });
});
