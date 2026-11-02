import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import { DreamProviderContext } from "./providers";
import { MockDreamProvider } from "../providers/MockDreamProvider";

describe("Dream app shell", () => {
  it("shows navigation while hardware is pending and labels the mock status only after its response", async () => {
    const provider = new MockDreamProvider();
    const hardware = await provider.getHardware();
    let releaseHardware!: () => void;
    const pending = new Promise<void>(resolve => { releaseHardware = resolve; });
    vi.spyOn(provider, "getHardware").mockImplementation(async () => { await pending; return hardware; });
    render(
      <DreamProviderContext.Provider value={provider}>
        <App />
      </DreamProviderContext.Provider>,
    );

    expect(screen.getByText("硬件状态")).toBeVisible();
    expect(screen.getByText("等待采样")).toBeVisible();
    expect(screen.queryByText("演示 / 模拟")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "生成" })).toBeVisible();
    for (const label of ["生成", "模型", "历史", "实验室", "显微镜", "设置"]) {
      const navigationButton = screen.getByRole("button", { name: label });
      expect(navigationButton).toBeVisible();
      expect(navigationButton).toHaveAttribute("aria-label", label);
      expect(navigationButton).toHaveAttribute("title", label);
    }
    await act(async () => releaseHardware());
    expect(screen.getByText("演示 / 模拟")).toBeVisible();
  });

  it("keeps the monitoring warning visible while submitting generation after a probe failure", async () => {
    const provider = new MockDreamProvider();
    let rejectHardware!: (reason: Error) => void;
    vi.spyOn(provider, "getHardware").mockReturnValue(new Promise<never>((_resolve, reject) => { rejectHardware = reject; }));
    const generate = vi.spyOn(provider, "generate");
    render(
      <DreamProviderContext.Provider value={provider}>
        <App />
      </DreamProviderContext.Provider>,
    );

    const warning = screen.getByRole("alert", { name: "硬件监控提示" });
    expect(warning).toHaveTextContent("尚无有效硬件采样");
    await act(async () => rejectHardware(new Error("Hardware probe failed")));
    expect(warning).toHaveTextContent("Hardware probe failed");
    expect(screen.getByRole("button", { name: "生成图像" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "生成图像" }));
    await waitFor(() => expect(generate).toHaveBeenCalledTimes(1));
    expect(warning).toBeVisible();
    expect(await screen.findByRole("button", { name: "取消生成" })).toBeVisible();
  });

  it("keeps the active generation session visible after navigating away and back", async () => {
    const provider = new MockDreamProvider();
    const getJob = provider.getJob.bind(provider);
    // Navigation must not race the demo provider's 520 ms automatic completion.
    vi.spyOn(provider, "getJob").mockImplementation(async (id) => ({
      ...await getJob(id),
      state: "sampling",
      progress: 50,
      message: "采样中",
      result: undefined,
    }));
    const cancelJob = vi.spyOn(provider, "cancelJob");
    render(
      <DreamProviderContext.Provider value={provider}>
        <App />
      </DreamProviderContext.Provider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "生成图像" }));
    expect(await screen.findByRole("button", { name: "取消生成" })).toBeVisible();
    expect(screen.getByText("批量队列 · 1 项")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "历史" }));
    expect(await screen.findByRole("heading", { name: "历史", level: 1 })).toBeVisible();
    expect(cancelJob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "生成" }));

    expect(await screen.findByRole("button", { name: "取消生成" })).toBeVisible();
    expect(screen.getByText("批量队列 · 1 项")).toBeVisible();
    expect(cancelJob).not.toHaveBeenCalled();
  });

  it("carries a history record back to the generation form for rerun", async () => {
    render(
      <DreamProviderContext.Provider value={new MockDreamProvider()}>
        <App />
      </DreamProviderContext.Provider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "历史" }));
    await screen.findByRole("heading", { name: "a serene mountain lake at sunrise" });
    fireEvent.click(screen.getByRole("button", { name: "重新生成此图" }));

    expect(await screen.findByRole("heading", { name: "生成" })).toBeVisible();
    expect(screen.getByRole("spinbutton", { name: "Width" })).toHaveValue(832);
    expect(screen.getByRole("spinbutton", { name: "Height" })).toHaveValue(1216);
    expect(screen.getByRole("spinbutton", { name: "Steps" })).toHaveValue(8);
  });

  it("promotes a completed lab experiment back to the generation form", async () => {
    render(
      <DreamProviderContext.Provider value={new MockDreamProvider()}>
        <App />
      </DreamProviderContext.Provider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "实验室" }));
    fireEvent.click(await screen.findByRole("button", { name: "运行实验" }));
    await screen.findByText(/实验完成/);
    fireEvent.click(screen.getByRole("button", { name: "提升为生成预设" }));

    expect(await screen.findByRole("heading", { name: "生成" })).toBeVisible();
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "正向提示词" }).value).toContain("mountain lake");
    expect(screen.getByRole("spinbutton", { name: "Steps" })).toHaveValue(20);
    expect(screen.getByRole("spinbutton", { name: "CFG" })).toHaveValue(4);
  });
});
