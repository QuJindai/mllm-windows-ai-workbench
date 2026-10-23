import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { BatchRetryActions, type BatchRetrySummary } from "./BatchRetryActions";

const parent: BatchRetrySummary = {
  id: "batch-parent", state: "failed",
  items: [{ state: "complete", resultDeleted: true }, { state: "failed" }, { state: "cancelled" }, { state: "queued" }],
};
beforeEach(() => sessionStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("only offers eligible items and disables both actions while the promise is pending", async () => {
  let finish!: () => void;
  const onRetry = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
  render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  expect(screen.getByRole("button", { name: "重试失败项（1）" })).toBeEnabled();
  const unfinished = screen.getByRole("button", { name: "继续未完成项（3）" });
  fireEvent.click(unfinished);
  fireEvent.click(unfinished);
  expect(onRetry).toHaveBeenCalledTimes(1);
  expect(onRetry).toHaveBeenCalledWith("batch-parent", { mode: "unfinished", idempotencyKey: expect.any(String) });
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  await act(async () => finish());
  expect(screen.getByRole("status")).toHaveTextContent(/已提交/);
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
});

it.each(["queued", "preparing", "sampling"] as const)("rejects actions for an active %s parent", state => {
  render(<BatchRetryActions batch={{ ...parent, state }} onRetry={async () => undefined} />);
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
});

it("does not count deleted completed results as unfinished", () => {
  render(<BatchRetryActions batch={{ ...parent, state: "complete", items: [{ state: "complete", resultDeleted: true }] }} onRetry={async () => undefined} />);
  expect(screen.getByRole("button", { name: "重试失败项（0）" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "继续未完成项（0）" })).toBeDisabled();
});

it("keeps the same idempotency key after a lost response and component remount", async () => {
  const onRetry = vi.fn().mockRejectedValueOnce(new Error("连接中断，请重试")).mockResolvedValue({ id: "new-batch" });
  const mounted = render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: "重试失败项（1）" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接中断，请重试");
  const first = onRetry.mock.calls[0];
  expect(first[1].idempotencyKey.length).toBeGreaterThan(0);
  mounted.unmount();
  render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: "重试失败项（1）" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/已提交/));
  expect(onRetry.mock.calls[1]).toEqual(first);
});

it("shows parent provenance with human-readable original indices", () => {
  render(<BatchRetryActions batch={{ ...parent, parentBatchId: "batch-original", originalItemIndices: [1, 3] }} onRetry={async () => undefined} />);
  expect(screen.getByText(/来源批次：batch-original/)).toBeVisible();
  expect(screen.getByText(/原批次图片：2、4/)).toBeVisible();
});

it("does not let an old parent's rejected promise overwrite a new parent's actions", async () => {
  let reject!: (reason: Error) => void;
  const onRetry = vi.fn(() => new Promise<void>((_, fail) => { reject = fail; }));
  const view = render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: "重试失败项（1）" }));
  view.rerender(<BatchRetryActions batch={{ ...parent, id: "batch-other" }} onRetry={onRetry} />);
  expect(screen.getByRole("button", { name: "重试失败项（1）" })).toBeEnabled();
  await act(async () => reject(new Error("旧批次失败")));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("honors an external disabled state", () => {
  render(<BatchRetryActions batch={parent} disabled onRetry={async () => undefined} />);
  for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
});

it.each(["failed", "unfinished"] as const)("locks the unresolved %s operation across mode switches and remounts", async mode => {
  const onRetry = vi.fn().mockRejectedValueOnce(new Error("response lost")).mockResolvedValue(undefined);
  const label = mode === "failed" ? "重试失败项（1）" : "继续未完成项（3）";
  const other = mode === "failed" ? "继续未完成项（3）" : "重试失败项（1）";
  const view = render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  fireEvent.click(screen.getByRole("button", { name: label }));
  await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: other })).toBeDisabled();
  view.unmount();
  render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  expect(screen.getByRole("button", { name: other })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: other }));
  expect(onRetry).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: label }));
  await waitFor(() => expect(onRetry).toHaveBeenCalledTimes(2));
  expect(onRetry.mock.calls[1]).toEqual(onRetry.mock.calls[0]);
});

it("migrates a single legacy mode key without allocating a replacement", async () => {
  sessionStorage.setItem("dream.batchRetry:batch-parent:failed", "lost-legacy-request");
  const onRetry = vi.fn().mockResolvedValue(undefined);
  render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  expect(screen.getByRole("button", { name: "继续未完成项（3）" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "重试失败项（1）" }));
  await waitFor(() => expect(onRetry).toHaveBeenCalledWith("batch-parent", { mode: "failed", idempotencyKey: "lost-legacy-request" }));
});

it("fails closed when both legacy modes may already have accepted children", () => {
  sessionStorage.setItem("dream.batchRetry:batch-parent:failed", "first");
  sessionStorage.setItem("dream.batchRetry:batch-parent:unfinished", "second");
  const onRetry = vi.fn();
  render(<BatchRetryActions batch={parent} onRetry={onRetry} />);
  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled(); fireEvent.click(button);
  }
  expect(screen.getByRole("alert")).toHaveTextContent(/批次历史/);
  expect(onRetry).not.toHaveBeenCalled();
});

it.each(["null", "{}", "{broken", JSON.stringify({ mode: ["failed"], idempotencyKey: "key" })])(
  "does not reset an unreadable operation to a fresh key: %s", raw => {
    sessionStorage.setItem("dream.batchRetry:batch-parent", raw);
    render(<BatchRetryActions batch={parent} onRetry={async () => undefined} />);
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
    expect(screen.getByRole("alert")).toBeVisible();
  },
);
