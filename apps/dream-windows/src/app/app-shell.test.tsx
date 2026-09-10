import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

    await waitFor(() => expect(screen.getByText("硬件状态")).toBeVisible());
    expect(screen.getByRole("heading", { name: "生成" })).toBeVisible();
    for (const label of ["生成", "模型", "历史", "实验室", "显微镜", "设置"]) {
      const navigationButton = screen.getByRole("button", { name: label });
      expect(navigationButton).toBeVisible();
      expect(navigationButton).toHaveAttribute("aria-label", label);
      expect(navigationButton).toHaveAttribute("title", label);
    }
    expect(screen.getByText("演示 / 模拟")).toBeVisible();
  });

  it("surfaces a hardware probe failure and disables generation", async () => {
    class HardwareFailureProvider extends MockDreamProvider {
      override async getHardware(): Promise<never> {
        throw new Error("Hardware probe failed");
      }
    }

    render(
      <DreamProviderContext.Provider value={new HardwareFailureProvider()}>
        <App />
      </DreamProviderContext.Provider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Hardware probe failed");
    expect(screen.getByRole("button", { name: "生成图像" })).toBeDisabled();
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
