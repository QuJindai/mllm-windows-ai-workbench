import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IdentityBatch, IdentityJob, IdentityRequest } from "../../domain/identity";
import { IdentityPage } from "./IdentityPage";
import { identityApi } from "../../providers/identity-api";

// Keep the page, workspace hook, retry controls, and HTTP provider real. Only
// transport is replaced: these tests catch missing selection, swallowed errors,
// changed retry keys, duplicate submissions, and polling the wrong batch.
const request: IdentityRequest = {
  modelId: "realistic-vision-v5.1-faceid", referenceId: "ref-retry", faceIndex: 0,
  prompt: "A clothed portrait in a garden", negativePrompt: "blur", seed: 42,
  width: 512, height: 768, steps: 10, cfg: 5.5, identityStrength: .82,
  structureStrength: .9, faceLoraStrength: .55, facePolish: false, faceRestoreStrength: 1,
};
const parent: IdentityBatch = {
  id: "batch-aaaaaaaaaaaaaaaaaaaaaaaa", state: "cancelled",
  request: { request, count: 2, stepValues: [10, 20], previewEvery: 0 },
  items: [
    { id: "identity-completed", state: "complete", progress: 100, message: "完成", request,
      result: { imageUrl: "/api/identity/jobs/identity-completed/image", metadata: { seed: 42 } }, error: null },
    { id: "identity-failed", state: "failed", progress: 0, message: "失败",
      request: { ...request, steps: 20 }, result: null, error: "controlled failure" },
    { id: "identity-cancelled-1", state: "cancelled", progress: 0, message: "已取消",
      request: { ...request, seed: 43 }, result: null, error: null },
    { id: "identity-cancelled-2", state: "cancelled", progress: 0, message: "已取消",
      request: { ...request, seed: 43, steps: 20 }, result: null, error: null },
  ],
  currentItem: 2, totalItems: 4, completedItems: 1, step: 0, totalSteps: 20,
  progress: 25, stage: "已取消", elapsedMs: 2000, etaMs: null, previewUrl: null,
  error: null, createdAt: "2026-10-23T10:00:00Z", updatedAt: "2026-10-23T10:01:00Z",
};
const childId = "batch-bbbbbbbbbbbbbbbbbbbbbbbb";
const retryUrl = `/api/identity/batches/${parent.id}/retry`;
type Mode = "failed" | "unfinished";
type Call = { url: string; method: string; body?: unknown; credentials?: RequestCredentials; contentType: string | null };
let calls: Call[];
let child: IdentityBatch | null;
let source: IdentityBatch;
let respondToRetry: (body: { mode: Mode; idempotencyKey: string }) => Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
const posts = () => calls.filter(call => call.method === "POST");
const batchButton = (id: string) => screen.getByRole("button", { name: `打开人物批次 ${id}` });
const retryControls = () => within(screen.getByRole("region", { name: "批次重试" }));

function acceptRetry(mode: Mode) {
  const indices = source.items.flatMap((item, index) =>
    (mode === "failed" ? item.state === "failed" : item.state !== "complete") ? [index] : []);
  child = {
    ...structuredClone(source), id: childId, parentBatchId: parent.id, originalItemIndices: indices,
    state: "queued", currentItem: 0, totalItems: indices.length, completedItems: 0,
    progress: 0, stage: "等待重试", elapsedMs: 0,
    items: indices.map(index => ({ ...structuredClone(source.items[index]), id: `identity-retry-${index}`,
      state: "queued", progress: 0, message: "排队中", result: null, error: null })),
  };
  return json(child);
}

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); calls = []; child = null; source = structuredClone(parent);
  respondToRetry = async body => acceptRetry(body.mode);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body, credentials: init?.credentials, contentType: new Headers(init?.headers).get("Content-Type") });
    if (url === retryUrl && method === "POST") return respondToRetry(body);
    if (method !== "GET") throw new Error(`Unexpected write: ${method} ${url}`);
    if (url === "/api/identity/status") return json({ ready: true, modelName: "Realistic Vision V5.1", message: "运行环境就绪", loras: [] });
    if (url === "/api/identity/references") return json([{ id: "ref-retry", referenceKind: "faceid", name: "合成参考.png",
      imageUrl: "/api/identity/references/ref-retry/image", faces: [{ index: 0, box: [0, 0, 100, 100] }] }]);
    if (url === "/api/identity/profiles") return json([]);
    if (url === "/api/identity/jobs") return json([...source.items, ...(child?.items ?? [])]);
    if (url === "/api/identity/batches") return json(child ? [child, source] : [source]);
    if (url === `/api/identity/batches/${parent.id}`) return json(source);
    if (child && url === `/api/identity/batches/${child.id}`) return json(child);
    throw new Error(`Unexpected read: ${url}`);
  }));
});

it("never creates overlapping children by switching modes after an accepted response is lost", async () => {
  source.items = source.items.map(item => item.state === "complete" ? item : { ...item, state: "failed" });
  const accepted = new Map<string, IdentityBatch>();
  respondToRetry = async body => {
    if (accepted.has(body.idempotencyKey)) return json(accepted.get(body.idempotencyKey));
    const result: IdentityBatch = await acceptRetry(body.mode).json();
    result.id = accepted.size ? "batch-cccccccccccccccccccccccc" : childId;
    accepted.set(body.idempotencyKey, result);
    child = null; // Acceptance succeeded, but the browser has not read it yet.
    if (accepted.size === 1) throw new TypeError("accepted response lost");
    return json(result);
  };
  const view = render(<StrictMode><IdentityPage /></StrictMode>);
  fireEvent.click(await screen.findByRole("button", { name: `打开人物批次 ${parent.id}` }));
  await waitFor(() => expect(retryControls().getByRole("button", { name: "重试失败项（3）" })).toBeEnabled());
  fireEvent.click(retryControls().getByRole("button", { name: "重试失败项（3）" }));
  await retryControls().findByRole("alert");
  await act(async () => fireEvent.click(retryControls().getByRole("button", { name: "继续未完成项（3）" })));
  expect(posts()).toHaveLength(1);
  expect(accepted.size).toBe(1);
  const first = posts()[0];

  // Refresh now discovers the queued child: recovery must work despite the
  // workspace's active-generation lock, without making a fresh request key.
  child = accepted.values().next().value!;
  view.unmount();
  render(<StrictMode><IdentityPage /></StrictMode>);
  await waitFor(() => expect(batchButton(childId)).toBeInTheDocument());
  expect(retryControls().getByRole("button", { name: "继续未完成项（3）" })).toBeDisabled();
  fireEvent.click(retryControls().getByRole("button", { name: "重试失败项（3）" }));
  await expectChildSelected([1, 2, 3]);
  expect(posts()).toEqual([first, first]);
  expect(accepted.size).toBe(1);
});

it("enforces the parent operation at the API boundary and reads the confirmed child without another POST", async () => {
  const original = { mode: "failed" as const, idempotencyKey: "original-attempt" };
  await identityApi.retryBatch(parent.id, original);
  await expect(identityApi.retryBatch(parent.id, { mode: "unfinished", idempotencyKey: "different-attempt" })).rejects.toThrow();
  await expect(identityApi.retryBatch(parent.id, { mode: "failed", idempotencyKey: "different-attempt" })).rejects.toThrow();
  const recovered = await identityApi.retryBatch(parent.id, original);
  expect(recovered.id).toBe(childId);
  expect(posts()).toHaveLength(1);
  expect(calls.at(-1)).toMatchObject({ url: `/api/identity/batches/${childId}`, method: "GET" });
});

it("never submits if the operation cannot be persisted before HTTP", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage unavailable"); });
  await expect(identityApi.retryBatch(parent.id, { mode: "failed", idempotencyKey: "must-not-send" })).rejects.toThrow("storage unavailable");
  expect(calls).toHaveLength(0);
});

it("keeps the operation locked when the server returns an unrelated child", async () => {
  respondToRetry = async mode => {
    const result = await acceptRetry(mode.mode).json();
    return json({ ...result, parentBatchId: "batch-unrelated" });
  };
  const original = { mode: "failed" as const, idempotencyKey: "keep-after-bad-receipt" };
  await expect(identityApi.retryBatch(parent.id, original)).rejects.toThrow(/来源未确认/);
  await expect(identityApi.retryBatch(parent.id, { mode: "unfinished", idempotencyKey: "new-key" })).rejects.toThrow();
  expect(posts()).toHaveLength(1);
  respondToRetry = async body => acceptRetry(body.mode);
  const recovered = await identityApi.retryBatch(parent.id, original);
  expect(recovered.id).toBe(childId);
  expect(posts().map(call => call.body)).toEqual([original, original]);
});

it("never falls back to a fresh POST if reading a confirmed child fails", async () => {
  const original = { mode: "failed" as const, idempotencyKey: "confirmed-operation" };
  await identityApi.retryBatch(parent.id, original);
  const savedChild = child;
  child = null;
  await expect(identityApi.retryBatch(parent.id, original)).rejects.toThrow();
  expect(posts()).toHaveLength(1);
  child = savedChild;
  expect((await identityApi.retryBatch(parent.id, original)).id).toBe(childId);
  expect(posts()).toHaveLength(1);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear(); });

async function openParent() {
  const view = render(<StrictMode><IdentityPage /></StrictMode>);
  fireEvent.click(await screen.findByRole("button", { name: `打开人物批次 ${parent.id}` }));
  await waitFor(() => expect(retryControls().getByRole("button", { name: "重试失败项（1）" })).toBeEnabled());
  expect(batchButton(parent.id)).toHaveAttribute("aria-pressed", "true");
  return view;
}

async function expectChildSelected(indices: number[]) {
  await waitFor(() => expect(batchButton(childId)).toHaveAttribute("aria-pressed", "true"));
  expect(batchButton(parent.id)).toHaveAttribute("aria-pressed", "false");
  expect(retryControls().getByText(`来源批次：${parent.id}`)).toBeVisible();
  expect(retryControls().getByText(`原批次图片：${indices.map(index => index + 1).join("、")}`)).toBeVisible();
  expect(JSON.parse(localStorage.getItem("dream.identity.last-view.v1")!)).toEqual({ kind: "batch", id: childId });
  expect(localStorage.getItem("dream.identity.last-batch.v1")).toBe(childId);
  expect(screen.getByLabelText("场景提示词")).toHaveValue("A clothed portrait in a garden");
  expect(screen.getByLabelText("种子")).toHaveValue("42");
  expect(screen.getByLabelText("步数")).toHaveValue(10);
}

it.each([
  ["failed", "重试失败项（1）", [1]],
  ["unfinished", "继续未完成项（3）", [1, 2, 3]],
] as const)("clicking %s selects, persists, and polls the returned child instead of resubmitting the parent", async (mode, label, indices) => {
  await openParent();
  // An edited form must not replace the frozen request returned by retry.
  fireEvent.change(screen.getByLabelText("场景提示词"), { target: { value: "Unsubmitted draft" } });
  fireEvent.change(screen.getByLabelText("种子"), { target: { value: "99" } });
  fireEvent.click(retryControls().getByRole("button", { name: label }));
  await expectChildSelected([...indices]);
  expect(posts()).toEqual([{ url: retryUrl, method: "POST", body: { mode, idempotencyKey: expect.any(String) },
    credentials: "same-origin", contentType: "application/json" }]);
  expect((posts()[0].body as { idempotencyKey: string }).idempotencyKey).not.toBe("");
  expect(retryControls().getByRole("button", { name: /^继续未完成项/ })).toBeDisabled();

  const beforePoll = calls.length;
  child = { ...child!, state: "complete", completedItems: indices.length, progress: 100, stage: "重试完成",
    items: child!.items.map((item): IdentityJob => ({ ...item, state: "complete", progress: 100,
      result: { imageUrl: `/api/identity/jobs/${item.id}/image`, metadata: { seed: item.request.seed } } })) };
  await waitFor(() => expect(screen.getByRole("status", { name: "批次进度" })).toHaveTextContent(`已完成 ${indices.length} 张`), { timeout: 3000 });
  expect(calls.slice(beforePoll)).toEqual(expect.arrayContaining([expect.objectContaining({ url: `/api/identity/batches/${childId}`, method: "GET" })]));
  expect(calls.slice(beforePoll).some(call => call.url === `/api/identity/batches/${parent.id}`)).toBe(false);
  expect(posts()).toHaveLength(1);
  fireEvent.click(batchButton(parent.id));
  await waitFor(() => expect(batchButton(parent.id)).toHaveAttribute("aria-pressed", "true"));
  expect(screen.getByRole("article", { name: "已完成结果 identity-completed" })).toBeVisible();
  expect(screen.getByRole("status", { name: "批次进度" })).toHaveTextContent("已完成 1 张");
});

it.each(["http", "network"] as const)("a %s failure stays retryable, suppresses a double click, and reuses the same key after remount", async failure => {
  let finish!: () => void;
  respondToRetry = () => new Promise<Response>((resolve, reject) => {
    finish = () => failure === "http"
      ? resolve(json({ code: "DISK_SPACE_LOW", message: "磁盘空间不足，请释放空间后重试", retryable: true }, 507))
      : reject(new TypeError("连接中断"));
  });
  const view = await openParent();
  const button = retryControls().getByRole("button", { name: "重试失败项（1）" });
  fireEvent.click(button); fireEvent.click(button);
  expect(posts()).toHaveLength(1);
  const first = structuredClone(posts()[0]);
  expect(first.body).toEqual({ mode: "failed", idempotencyKey: expect.any(String) });
  expect((first.body as { idempotencyKey: string }).idempotencyKey).not.toBe("");
  for (const control of retryControls().getAllByRole("button")) expect(control).toBeDisabled();
  await act(async () => finish());
  expect(await retryControls().findByRole("alert")).toHaveTextContent(/重试未确认/);
  expect(screen.getByText(failure === "http" ? "磁盘空间不足，请释放空间后重试" : "连接中断")).toBeVisible();
  expect(button).toBeEnabled();
  expect(batchButton(parent.id)).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: `打开人物批次 ${childId}` })).not.toBeInTheDocument();
  expect(retryControls().getByRole("status")).not.toHaveTextContent(/已提交/);
  expect(posts()).toHaveLength(1);

  view.unmount();
  respondToRetry = async body => acceptRetry(body.mode);
  render(<StrictMode><IdentityPage /></StrictMode>);
  await waitFor(() => expect(retryControls().getByRole("button", { name: "重试失败项（1）" })).toBeEnabled());
  expect(posts()).toHaveLength(1); // Neither error handling nor restoration submits automatically.
  fireEvent.click(retryControls().getByRole("button", { name: "重试失败项（1）" }));
  await expectChildSelected([1]);
  expect(posts()).toEqual([first, first]);
  expect(retryControls().queryByRole("alert")).not.toBeInTheDocument();
});
