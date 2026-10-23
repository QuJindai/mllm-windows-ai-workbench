import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import "../../styles/global.css";
import "../shell.css";
import "../workstation.css";
import { OperationsDiagnostics } from "./OperationsDiagnostics";

function snapshot(status = "ok", freeBytes: number | null = 20 * 1024 ** 3) {
  return {
    schemaVersion: 1, service: "dream-web", timestamp: "2026-10-23T01:00:00+00:00",
    release: { status: "known", release: "p0-test-20261023", buildId: null, commit: null },
    disk: { status, freeBytes, warningBytes: 10 * 1024 ** 3, blockingBytes: 2 * 1024 ** 3, generationAllowed: freeBytes === null ? null : status !== "blocked" },
    checks: [{ id: "frontend", label: "前端入口", status: "missing", message: "C:\\Users\\Private secret" }],
    pendingWork: {
      source: "persisted-records",
      ordinary: { status: "known", pendingCount: 0 },
      identity: { status: "unknown", pendingCount: null },
      batches: { status: "known", pendingCount: 2 },
    },
    guidance: ["private-command --token secret"],
  };
}

function response(body: unknown, ok = true) {
  return { ok, json: async () => body };
}

afterEach(() => vi.unstubAllGlobals());

it("keeps diagnostics in a Settings card with readable controls and scoped definition-list layout", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(snapshot())));
  render(<><OperationsDiagnostics /><div className="surface-card" aria-label="Settings 标准卡片" /><button type="button">外部按钮</button><dl aria-label="外部列表"><dt>标签</dt><dd>值</dd></dl></>);
  await screen.findByText("p0-test-20261023");
  const card = screen.getByRole("region", { name: "运维诊断" });
  const settingsCard = getComputedStyle(screen.getByLabelText("Settings 标准卡片"));
  expect(getComputedStyle(card).padding).toBe(settingsCard.padding);
  expect(getComputedStyle(card).backgroundImage).toBe(settingsCard.backgroundImage);
  const refresh = getComputedStyle(screen.getByRole("button", { name: "刷新诊断" }));
  expect(refresh.backgroundColor).not.toBe(getComputedStyle(screen.getByRole("button", { name: "外部按钮" })).backgroundColor);
  expect(Number.parseFloat(refresh.minHeight)).toBeGreaterThanOrEqual(38);
  expect(getComputedStyle(card.querySelector("dl")!).display).toBe("grid");
  expect(getComputedStyle(card.querySelector("dd")!).marginLeft).toBe("0px");
  expect(getComputedStyle(card.querySelector("dd")!).overflowWrap).toBe("anywhere");
  expect(getComputedStyle(screen.getByLabelText("外部列表")).display).toBe("block");
});

it("loads safe diagnostics and distinguishes unknown counts from zero", async () => {
  const fetcher = vi.fn().mockResolvedValue(response(snapshot()));
  vi.stubGlobal("fetch", fetcher);
  const { container } = render(<OperationsDiagnostics />);
  expect(await screen.findByText("p0-test-20261023")).toBeVisible();
  expect(screen.getByText("20.00 GiB")).toBeVisible();
  expect(screen.getByText("普通任务：0")).toBeVisible();
  expect(screen.getByText("人物任务：未知")).toBeVisible();
  expect(screen.getByText("人物批次：2")).toBeVisible();
  expect(screen.getByText(/前端入口.*缺失/)).toBeVisible();
  expect(fetcher).toHaveBeenCalledWith("/api/operations", expect.objectContaining({ cache: "no-store", signal: expect.any(AbortSignal) }));
  expect(container.textContent).not.toMatch(/Private|secret|private-command/);
});

it.each([
  ["warning", 3 * 1024 ** 3, "空间偏低", "3.00 GiB"],
  ["blocked", 0, "已阻止新生成", "0.00 GiB"],
  ["unknown", null, "容量未知", "未知"],
])("renders %s capacity truthfully", async (status, bytes, label, value) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(snapshot(status, bytes))));
  render(<OperationsDiagnostics />);
  expect(await screen.findByText(label)).toBeVisible();
  expect(screen.getByLabelText("可用空间")).toHaveTextContent(value);
  expect(getComputedStyle(screen.getByText(label)).color).not.toBe(
    getComputedStyle(screen.getByText(/安装检查仅确认文件/)).color,
  );
});

it("clears stale diagnostics on refresh failure and supports retry without exposing errors", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response(snapshot("blocked", 0)))
    .mockRejectedValueOnce(new Error("C:\\Users\\Private secret"))
    .mockResolvedValueOnce(response(snapshot()));
  vi.stubGlobal("fetch", fetcher);
  const { container } = render(<OperationsDiagnostics />);
  expect(await screen.findByText("已阻止新生成")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "刷新诊断" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("诊断暂不可用");
  expect(screen.queryByText("已阻止新生成")).not.toBeInTheDocument();
  expect(container.textContent).not.toMatch(/Private|secret|0.00 GiB/);
  fireEvent.click(screen.getByRole("button", { name: "刷新诊断" }));
  expect(await screen.findByText("20.00 GiB")).toBeVisible();
});

it.each([
  response({ code: "error", message: "private-command secret" }, false),
  response({ ...snapshot(), disk: { status: "ok", freeBytes: null } }),
  response({ ...snapshot(), service: "other" }),
])("rejects unavailable or malformed responses without showing an invented status", async (reply) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply));
  const { container } = render(<OperationsDiagnostics />);
  expect(await screen.findByRole("alert")).toHaveTextContent("诊断暂不可用");
  expect(container.textContent).not.toMatch(/private-command|secret|GiB/);
});

it("does not display sensitive values placed inside release fields", async () => {
  const body = snapshot();
  body.release.release = "C:\\Users\\Private";
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
  const { container } = render(<OperationsDiagnostics />);
  expect(await screen.findByText("未提供")).toBeVisible();
  expect(container.textContent).not.toContain("Private");
});

it("aborts the request on unmount and keeps mock mode from contacting the backend", async () => {
  const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const { unmount } = render(<OperationsDiagnostics />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
  const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
  expect(screen.getByRole("button", { name: "刷新诊断" })).toBeDisabled();
  unmount();
  expect(signal.aborted).toBe(true);
  render(<OperationsDiagnostics enabled={false} />);
  expect(screen.getByText(/连接本地服务后可读取/)).toBeVisible();
  expect(fetcher).toHaveBeenCalledOnce();
});
