import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { IdentityPage } from "../../pages/IdentityPage";
import { DreamProviderContext } from "../../providers";
import type { DreamProvider } from "../../../providers/DreamProvider";
import type { IdentityBatch, IdentityJob } from "../../../domain/identity";
import { announceImageDeleted } from "../../image-deletion";

const request = { referenceId: "deletion-ref", faceIndex: 0, prompt: "合成删除验收", negativePrompt: "", seed: 42, width: 512, height: 512, steps: 28, cfg: 5.5, identityStrength: .82, structureStrength: .9, faceLoraStrength: .55, facePolish: false, faceRestoreStrength: 1 };
const makeJob = (id: string): IdentityJob => ({ id, state: "complete", progress: 100, message: "完成", request, result: { imageUrl: `/api/outputs/${id}.png`, metadata: {} }, error: null });
let jobs: IdentityJob[], batch: IdentityBatch, scope: DreamProvider;
let failDelete = false;
let heldJobs: Promise<Response> | null = null;
let deletes: string[];
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
beforeEach(() => {
  localStorage.clear(); scope = {} as DreamProvider; failDelete = false; heldJobs = null; deletes = [];
  jobs = [makeJob("history-first"), makeJob("history-sibling"), { ...makeJob("history-failed"), state: "failed", result: null, error: "测试失败" }];
  batch = { id: "history-batch", state: "complete", request: { request, count: 2, previewEvery: 0 }, items: jobs.slice(0, 2), totalItems: 2, completedItems: 2, currentItem: 2, step: 28, totalSteps: 28, progress: 100, stage: "完成", elapsedMs: 100, etaMs: null, previewUrl: null, error: null, createdAt: "2026-10-25", updatedAt: "2026-10-25" };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "DELETE") {
      deletes.push(url);
      if (failDelete) return json({ message: "测试删除失败" }, 503);
      const id = url.split("/").pop()!;
      if (url === "/api/identity/batches/history-batch") {
        const deletedJobIds = batch.items.map(item => item.id);
        jobs = jobs.map(job => deletedJobIds.includes(job.id) ? { ...job, historyDeleted: true } : job);
        batch = { ...batch, historyDeleted: true, items: batch.items.map(item => jobs.find(job => job.id === item.id)!) };
        return json({ deleted: id, deletedJobIds });
      }
      jobs = jobs.map(job => job.id === id ? { ...job, historyDeleted: true, resultDeleted: job.state === "complete" } : job);
      batch = { ...batch, items: batch.items.map(item => jobs.find(job => job.id === item.id)!) };
      return json({ deleted: id });
    }
    if (url === "/api/identity/status") return json({ ready: true, modelName: "Realistic Vision V5.1", message: "就绪", loras: [] });
    if (url === "/api/identity/references") return json([{ id: request.referenceId, name: "合成参考", imageUrl: "/reference.png", faces: [{ index: 0, box: [0, 0, 10, 10] }] }]);
    if (url === "/api/identity/profiles") return json([]);
    if (url === "/api/identity/jobs") return heldJobs ?? json(jobs);
    if (url.startsWith("/api/identity/jobs/")) return json(jobs.find(job => job.id === url.split("/").pop()));
    if (url === "/api/identity/batches") return json([batch]);
    if (url === "/api/identity/batches/history-batch") return json(batch);
    throw new Error(`Unexpected ${url}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
async function open() {
  const view = render(<DreamProviderContext.Provider value={scope}><IdentityPage /></DreamProviderContext.Provider>);
  await screen.findByRole("button", { name: "打开人物任务 history-first" });
  await waitFor(() => expect(screen.getByRole("button", { name: "刷新运行状态" })).toBeEnabled());
  return view;
}
async function remove(id: string, recordOnly = false) {
  const history = screen.getByRole("region", { name: "人物任务历史" });
  fireEvent.click(within(history).getByRole("button", { name: `${recordOnly ? "删除记录" : "删除图片"} ${id}` }));
  fireEvent.click(screen.getByRole("button", { name: recordOnly ? "确认删除记录" : "确认删除图片" }));
  await waitFor(() => expect(within(history).queryByRole("button", { name: `打开人物任务 ${id}` })).not.toBeInTheDocument());
}
it("deletes from task history, updates the selected result and batch, and stays deleted after refresh/remount", async () => {
  const view = await open();
  fireEvent.click(screen.getByRole("button", { name: "打开人物任务 history-first" }));
  await screen.findByRole("img", { name: "生成结果" });
  await remove("history-first");
  expect(screen.queryByRole("img", { name: "生成结果" })).not.toBeInTheDocument();
  expect(screen.getByText(/历史记录已删除/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开人物批次 history-batch" })).toHaveTextContent("可用 1 张 · 已删除 1 张");
  fireEvent.click(screen.getByRole("button", { name: "刷新运行状态" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "刷新运行状态" })).toBeEnabled());
  expect(screen.queryByRole("button", { name: "打开人物任务 history-first" })).not.toBeInTheDocument();
  view.unmount(); render(<DreamProviderContext.Provider value={scope}><IdentityPage /></DreamProviderContext.Provider>);
  await screen.findByRole("button", { name: "打开人物任务 history-sibling" });
  expect(screen.queryByRole("button", { name: "打开人物任务 history-first" })).not.toBeInTheDocument();
  expect(deletes).toEqual(["/api/identity/jobs/history-first"]);
});
it("does not revive an acknowledged deletion when an older refresh completes later", async () => {
  await open();
  let resolve!: (response: Response) => void;
  const stale = json(jobs);
  heldJobs = new Promise(done => { resolve = done; });
  fireEvent.click(screen.getByRole("button", { name: "刷新运行状态" }));
  await remove("history-first");
  await act(async () => { resolve(stale); });
  expect(screen.queryByRole("button", { name: "打开人物任务 history-first" })).not.toBeInTheDocument();
});
it("preserves a row after failed deletion and allows deleting failed records without an image", async () => {
  await open(); failDelete = true;
  const history = screen.getByRole("region", { name: "人物任务历史" });
  fireEvent.click(within(history).getByRole("button", { name: "删除图片 history-first" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除图片" }));
  await screen.findByText("测试删除失败");
  expect(screen.getByRole("button", { name: "打开人物任务 history-first" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "取消删除" }));
  failDelete = false;
  await remove("history-failed", true);
  expect(screen.getByRole("button", { name: "打开人物任务 history-first" })).toBeInTheDocument();
});
it("receives a deletion from another view and honors it even when mounted afterwards", async () => {
  const view = await open();
  fireEvent.click(screen.getByRole("button", { name: "打开人物批次 history-batch" }));
  await screen.findByRole("article", { name: "已完成结果 history-first" });
  act(() => announceImageDeleted("history-first", scope));
  expect(screen.queryByRole("article", { name: "已完成结果 history-first" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "打开人物任务 history-first" })).not.toBeInTheDocument();
  expect(screen.getByRole("article", { name: "已完成结果 history-sibling" })).toBeInTheDocument();
  view.unmount();
  render(<DreamProviderContext.Provider value={scope}><IdentityPage /></DreamProviderContext.Provider>);
  await screen.findByRole("button", { name: "打开人物任务 history-sibling" });
  expect(screen.queryByRole("button", { name: "打开人物任务 history-first" })).not.toBeInTheDocument();
});

it("deletes the entire batch and all its views, preserving unrelated jobs after remount", async () => {
  const view = await open();
  fireEvent.click(screen.getByRole("button", { name: "打开人物批次 history-batch" }));
  await screen.findByRole("article", { name: "已完成结果 history-first" });
  fireEvent.click(screen.getByRole("button", { name: "删除批次 history-batch" }));
  expect(screen.getByRole("dialog", { name: "删除人物批次" })).toHaveTextContent("2 项");
  fireEvent.click(screen.getByRole("button", { name: "确认删除批次" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "打开人物批次 history-batch" })).not.toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "打开人物任务 history-first" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "打开人物任务 history-sibling" })).not.toBeInTheDocument();
  expect(screen.queryByRole("article", { name: "已完成结果 history-first" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开人物任务 history-failed" })).toBeInTheDocument();
  expect(screen.getByText(/批次已删除/)).toBeInTheDocument();
  view.unmount();
  render(<DreamProviderContext.Provider value={scope}><IdentityPage /></DreamProviderContext.Provider>);
  await screen.findByRole("button", { name: "打开人物任务 history-failed" });
  expect(screen.queryByRole("button", { name: "打开人物批次 history-batch" })).not.toBeInTheDocument();
});

it("keeps the batch and every child visible when batch deletion fails", async () => {
  await open(); failDelete = true;
  fireEvent.click(screen.getByRole("button", { name: "删除批次 history-batch" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除批次" }));
  await screen.findByText("测试删除失败");
  expect(screen.getByRole("button", { name: "打开人物批次 history-batch" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "打开人物任务 history-first" })).toBeInTheDocument();
});

it("removes an empty batch when its final individual record is deleted", async () => {
  await open();
  await remove("history-first");
  expect(screen.getByRole("button", { name: "打开人物批次 history-batch" })).toBeInTheDocument();
  await remove("history-sibling");
  expect(screen.queryByRole("button", { name: "打开人物批次 history-batch" })).not.toBeInTheDocument();
});
