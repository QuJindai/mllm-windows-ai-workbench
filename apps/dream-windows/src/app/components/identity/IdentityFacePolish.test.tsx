import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IdentityPage } from "../../pages/IdentityPage";
import { identityApi } from "../../../providers/identity-api";

// Legacy wire fixtures deliberately omit both new request fields.
const legacyRequest = {
  referenceId: "ref-a", faceIndex: 0, prompt: "窗边肖像", negativePrompt: "模糊", seed: 42,
  width: 512, height: 768, steps: 28, cfg: 5.5, identityStrength: 0.82, structureStrength: 0.9, faceLoraStrength: 0.55,
};
type WireRequest = typeof legacyRequest & { facePolish?: boolean; faceRestoreStrength?: number };
type WireJob = {
  id: string; state: "complete" | "sampling"; progress: number; message: string; request: WireRequest;
  result: { imageUrl: string; metadata: Record<string, unknown> } | null; error: null;
};
const originalUrl = "/api/identity/jobs/job-a/original";
const finalUrl = "/api/outputs/job-a.png";
const makeJob = (request: WireRequest = legacyRequest, metadata: Record<string, unknown> = {}): WireJob => ({
  id: "job-a", state: "complete", progress: 100, message: "生成完成", request,
  result: { imageUrl: finalUrl, metadata }, error: null,
});
function makeBatch(job: WireJob) {
  return { id: "batch-a", state: job.state, request: { profileId: "example", request: job.request, count: 1, previewEvery: 0 },
    items: [job], currentItem: 1, totalItems: 1, completedItems: job.state === "complete" ? 1 : 0,
    step: 28, totalSteps: 28, progress: job.progress, stage: job.message, elapsedMs: 15000, etaMs: null,
    previewUrl: null, error: null, createdAt: "2026-09-20", updatedAt: "2026-09-20" };
}
let capability: { ready: boolean; message: string } | undefined;
let profileDefaults: WireRequest;
let jobs: WireJob[];
let batches: ReturnType<typeof makeBatch>[];
let writes: Array<{ url: string; body: Partial<WireRequest> & { request?: WireRequest; jobId?: string } }>;
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
const profile = () => ({ id: "example", name: "Example", referenceId: "ref-a", faceIndex: 0, state: "ready", defaults: profileDefaults, error: null, createdAt: "2026-09-20", updatedAt: "2026-09-20" });

beforeEach(() => {
  localStorage.clear(); capability = { ready: true, message: "修脸可用" };
  profileDefaults = { ...legacyRequest }; jobs = [makeJob()]; batches = []; writes = [];
  // Only HTTP is replaced: exercise the real form, storage, restoration and adapter.
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    if (method === "POST") writes.push({ url, body });
    if (url === "/api/identity/status") return json({ ready: true, modelName: "Realistic Vision V5.1", message: "运行环境就绪", loras: [], ...(capability ? { facePolish: capability } : {}) });
    if (url === "/api/identity/references") return json([{ id: "ref-a", name: "测试参考", imageUrl: "/api/identity/references/ref-a/image", faces: [{ index: 0, box: [0, 0, 100, 100] }] }]);
    if (url === "/api/identity/profiles") return json([profile()]);
    if (url === "/api/identity/profiles/example/preset") {
      profileDefaults = { ...jobs.find((job) => job.id === body.jobId)!.request }; return json(profile());
    }
    if (url === "/api/identity/profiles/example") return json(profile());
    if (url === "/api/identity/jobs") return json(jobs);
    if (url.startsWith("/api/identity/jobs/")) return json(jobs.find((job) => job.id === url.split("/")[4]));
    if (url === "/api/identity/generate") return json(makeJob(body));
    if (url === "/api/identity/batches" && method === "POST") {
      jobs = [makeJob(body.request)]; batches = [{ ...makeBatch(jobs[0]), request: body }]; return json(batches[0]);
    }
    if (url === "/api/identity/batches") return json(batches);
    if (url === "/api/identity/batches/batch-a") return json(batches[0]);
    throw new Error(`Unexpected HTTP ${method} ${url}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const polish = () => screen.getByRole("checkbox", { name: "生成后修脸（可选）" });
const generate = () => screen.getByRole("button", { name: "生成人物图像" });
async function open(replay?: { id: string; revision: number }) {
  const view = render(<IdentityPage replay={replay} />);
  await screen.findByText("Realistic Vision V5.1");
  await waitFor(() => expect(screen.getByLabelText("场景提示词")).toBeEnabled());
  return view;
}
function prepare() {
  fireEvent.change(screen.getByLabelText("选择参考照"), { target: { value: "ref-a" } });
  fireEvent.change(screen.getByLabelText("场景提示词"), { target: { value: "窗边肖像" } });
}
async function selectProfile() {
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "example" } });
  await waitFor(() => expect(screen.getByLabelText("选择参考照")).toHaveValue("ref-a"));
  await waitFor(() => expect(generate()).toBeEnabled());
}
const optedIn = { ...legacyRequest, facePolish: true, faceRestoreStrength: 0.35 };

describe("optional identity face polish", () => {
  it.each([false, true])("starts OFF and submits explicit false/1 with an old draft: %s", async (oldDraft) => {
    if (oldDraft) localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "旧草稿", negativePrompt: "" }));
    await open(); prepare();
    expect(polish()).not.toBeChecked();
    expect(screen.queryByLabelText("面部细节修复强度")).not.toBeInTheDocument();
    fireEvent.click(generate());
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: false, faceRestoreStrength: 1 });
  });

  it("preserves opt-in and strength in an unsent draft across remount", async () => {
    const view = await open(); prepare(); fireEvent.click(polish());
    fireEvent.change(screen.getByLabelText("面部细节修复强度"), { target: { value: "0.35" } });
    expect(screen.getByText(/身份回贴.*面部细节修复/)).toBeVisible();
    view.unmount(); await open();
    expect(polish()).toBeChecked();
    expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.35);
    expect(writes).toHaveLength(0);
  });

  it("preserves a Example draft only for that selected profile and never enables an old preset on explicit selection", async () => {
    const view = await open(); await selectProfile();
    expect(polish()).not.toBeChecked();
    fireEvent.click(polish()); fireEvent.change(screen.getByLabelText("面部细节修复强度"), { target: { value: "0.35" } });
    view.unmount(); await open();
    expect(polish()).toBeChecked(); expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.35);
    fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "" } });
    await selectProfile();
    expect(polish()).not.toBeChecked();
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: false, faceRestoreStrength: 1 });
  });

  it.each([undefined, { ready: false, message: "缺少 inswapper 模型" }])("keeps baseline generation usable when polish is unavailable (%j)", async (value) => {
    capability = value; await open(); prepare();
    expect(polish()).toBeDisabled(); expect(polish()).not.toBeChecked();
    expect(screen.getByText(value?.message ?? /服务未报告修脸能力/)).toBeVisible();
    expect(generate()).toBeEnabled();
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request?.facePolish).toBe(false);
  });

  it("preserves unavailable opt-in, requires explicit OFF, and permits generation after switching OFF", async () => {
    capability = { ready: false, message: "GFPGAN 不可用" };
    jobs = [makeJob(optedIn)]; await open({ id: "job-a", revision: 1 });
    expect(polish()).toBeChecked(); expect(polish()).toBeEnabled(); expect(generate()).toBeDisabled();
    expect(screen.getByText(/关闭.*修脸.*继续生成/)).toBeVisible();
    fireEvent.click(polish()); expect(generate()).toBeEnabled(); expect(polish()).toBeDisabled();
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: false, faceRestoreStrength: 0.35 });
  });

  it("restores availability on status refresh without opting in automatically", async () => {
    capability = undefined; await open(); prepare(); expect(polish()).toBeDisabled();
    capability = { ready: true, message: "修脸可用" };
    fireEvent.click(screen.getByRole("button", { name: "刷新运行状态" }));
    await waitFor(() => expect(polish()).toBeEnabled()); expect(polish()).not.toBeChecked();
  });

  it.each([0, 0.35, 1])("round-trips enabled requests and strength %s through batch submission and replay", async (strength) => {
    const view = await open(); prepare(); fireEvent.click(polish());
    fireEvent.change(screen.getByLabelText("面部细节修复强度"), { target: { value: String(strength) } });
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: true, faceRestoreStrength: strength });
    view.unmount(); await open({ id: "job-a", revision: 1 });
    expect(polish()).toBeChecked(); expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(strength);
    expect(writes).toHaveLength(1);
  });

  it("round-trips explicit options through the single-job API", async () => {
    const job = await identityApi.generate(optedIn);
    expect(job.request).toMatchObject({ facePolish: true, faceRestoreStrength: 0.35 });
    expect(writes).toEqual([{ url: "/api/identity/generate", body: optedIn }]);
  });

  it.each(["", "-0.01", "1.01"])("blocks invalid enabled strength %j but permits OFF generation", async (value) => {
    await open(); prepare(); fireEvent.click(polish());
    fireEvent.change(screen.getByLabelText("面部细节修复强度"), { target: { value } });
    expect(generate()).toBeDisabled(); expect(screen.getByText(/修复强度.*0.*1/)).toBeVisible();
    fireEvent.click(polish()); expect(generate()).toBeEnabled();
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: false, faceRestoreStrength: 1 });
  });

  it("replays old jobs as OFF/1 even when the current draft opted in", async () => {
    localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "新草稿", negativePrompt: "", facePolish: true, faceRestoreStrength: 0.35 }));
    await open({ id: "job-a", revision: 1 }); expect(polish()).not.toBeChecked();
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: false, faceRestoreStrength: 1 });
  });

  it.each(["job", "batch"])("does not apply another view's polish draft when restoring an old %s", async (kind) => {
    localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "另一人物草稿", negativePrompt: "", facePolish: true, faceRestoreStrength: 0.35, profileId: "other", polishContext: "profile:other" }));
    if (kind === "batch") { batches = [makeBatch(jobs[0])]; localStorage.setItem("dream.identity.last-batch.v1", "batch-a"); }
    else localStorage.setItem("dream.identity.last-job.v1", "job-a");
    await open(); expect(polish()).not.toBeChecked();
    fireEvent.click(generate()); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body.request).toMatchObject({ facePolish: false, faceRestoreStrength: 1 });
  });

  it("does not let an old text-only draft switch OFF a saved opted-in job", async () => {
    jobs = [makeJob(optedIn)]; localStorage.setItem("dream.identity.last-job.v1", "job-a");
    localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "旧提示词草稿", negativePrompt: "" }));
    await open(); expect(polish()).toBeChecked();
    expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.35);
    expect(screen.getByLabelText("场景提示词")).toHaveValue("旧提示词草稿");
  });

  it("restores edited polish options for the same completed job on remount", async () => {
    const view = await open({ id: "job-a", revision: 1 });
    fireEvent.click(polish()); fireEvent.change(screen.getByLabelText("面部细节修复强度"), { target: { value: "0.6" } });
    view.unmount(); await open(); expect(polish()).toBeChecked();
    expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.6); expect(writes).toHaveLength(0);
  });

  it("loads an opted-in server preset and saves the chosen job preset without discarding its options", async () => {
    profileDefaults = { ...optedIn }; jobs = [makeJob({ ...optedIn, faceRestoreStrength: 0.6 })];
    const view = await open(); await selectProfile();
    expect(polish()).toBeChecked(); expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.35);
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-a" }));
    const save = await screen.findByRole("button", { name: "将 job-a 存为人物预设" });
    await waitFor(() => expect(save).toBeEnabled()); fireEvent.click(save);
    await screen.findByText("已保存人物预设，不改变身份特征。");
    expect(writes).toEqual([{ url: "/api/identity/profiles/example/preset", body: { jobId: "job-a" } }]);
    view.unmount(); await open();
    fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "" } }); await selectProfile();
    expect(polish()).toBeChecked(); expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.6);
  });

  it.each(["completed", "failed"])("keeps %s result links readable and underlined on dark cards", async (status) => {
    jobs = [makeJob(optedIn, { facePolish: { enabled: true, status, originalImageUrl: originalUrl } })];
    await open({ id: "job-a", revision: 1 });
    const names = status === "completed" ? ["打开生成原图", "打开修脸结果"] : ["打开生成原图"];
    for (const name of names) {
      const link = screen.getByRole("link", { name });
      const style = window.getComputedStyle(link);
      expect(style.color).toBe("rgb(50, 199, 255)");
      expect(style.textDecorationLine).toBe("underline");
    }
  });

  it.each(["job", "batch"])("shows original/final switches and distinct links on completed %s results", async (kind) => {
    jobs = [makeJob(optedIn, { facePolish: { enabled: true, status: "completed", originalImageUrl: originalUrl, restoreStrength: 0.35 } })];
    if (kind === "batch") { batches = [makeBatch(jobs[0])]; localStorage.setItem("dream.identity.last-batch.v1", "batch-a"); }
    await open(kind === "job" ? { id: "job-a", revision: 1 } : undefined);
    const panel = within(screen.getByRole("region", { name: "原图与修脸结果 job-a" }));
    expect(panel.getByText("修脸完成")).toBeVisible();
    const image = panel.getByRole("img", { name: "修脸结果" });
    const finalLink = panel.getByRole("link", { name: "打开修脸结果" }).getAttribute("href")!;
    expect(new URL(finalLink, "http://localhost").pathname).toBe(finalUrl);
    expect(new URL(finalLink, "http://localhost").search).not.toBe("");
    expect(image).toHaveAttribute("src", finalLink);
    expect(panel.getByRole("link", { name: "打开生成原图" })).toHaveAttribute("href", originalUrl);
    fireEvent.click(panel.getByRole("button", { name: "查看生成原图" }));
    expect(panel.getByRole("img", { name: "生成原图" })).toHaveAttribute("src", originalUrl);
    expect(panel.queryByRole("img", { name: "修脸结果" })).not.toBeInTheDocument();
    fireEvent.click(panel.getByRole("button", { name: "查看修脸结果" }));
    expect(panel.getByRole("img", { name: "修脸结果" })).toHaveAttribute("src", finalLink);
  });

  it.each(["job", "batch"])("prominently reports polish failure on a normal completed %s and keeps only the original", async (kind) => {
    jobs = [makeJob(optedIn, { facePolish: { enabled: true, status: "failed", originalImageUrl: originalUrl, message: "GFPGAN 执行失败" } })];
    if (kind === "batch") { batches = [makeBatch(jobs[0])]; localStorage.setItem("dream.identity.last-batch.v1", "batch-a"); }
    await open(kind === "job" ? { id: "job-a", revision: 1 } : undefined);
    const alert = screen.getByRole("alert");
    expect(alert).toBeVisible(); expect(alert).toHaveTextContent("修脸失败，已保留原图"); expect(alert).toHaveTextContent("GFPGAN 执行失败");
    expect(screen.getByRole("img", { name: "保留的原图" })).toHaveAttribute("src", originalUrl);
    expect(screen.getByRole("link", { name: "打开生成原图" })).toHaveAttribute("href", originalUrl);
    expect(screen.queryByText("修脸完成")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看修脸结果" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "打开修脸结果" })).not.toBeInTheDocument();
    expect(generate()).toBeEnabled();
  });

  it("clears image error and comparison state on a different job without reusing the prior cached image", async () => {
    jobs = [makeJob(optedIn, { facePolish: { enabled: true, status: "completed", originalImageUrl: originalUrl } })];
    jobs.push({ ...makeJob(optedIn, { facePolish: { enabled: true, status: "completed", originalImageUrl: "/api/identity/jobs/job-b/original" } }), id: "job-b" });
    const view = await open({ id: "job-a", revision: 1 });
    const firstUrl = screen.getByRole("img", { name: "修脸结果" }).getAttribute("src");
    fireEvent.error(screen.getByRole("img", { name: "修脸结果" }));
    fireEvent.click(screen.getByRole("button", { name: "查看生成原图" }));
    expect(screen.getByRole("img", { name: "生成原图" })).toBeVisible();
    view.rerender(<IdentityPage replay={{ id: "job-b", revision: 2 }} />);
    await screen.findByRole("region", { name: "原图与修脸结果 job-b" });
    expect(screen.getByRole("img", { name: "修脸结果" }).getAttribute("src")).not.toBe(firstUrl);
    expect(screen.queryByText("结果文件已删除或不可用")).not.toBeInTheDocument();
  });

  it("keeps active batch options frozen and displays the returned face polish stages", async () => {
    jobs = [{ ...makeJob(optedIn), state: "sampling", progress: 99, message: "身份回贴", result: null }];
    batches = [makeBatch(jobs[0])]; localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "草稿", negativePrompt: "", facePolish: false, faceRestoreStrength: 1 }));
    render(<IdentityPage />); await screen.findByText("当前阶段：身份回贴");
    expect(polish()).toBeChecked(); expect(polish()).toBeDisabled();
    expect(screen.getByLabelText("面部细节修复强度")).toHaveValue(0.35);
    batches[0].stage = "面部细节修复";
    await screen.findByText("当前阶段：面部细节修复", {}, { timeout: 2500 });
    expect(screen.queryByText("修脸完成")).not.toBeInTheDocument(); expect(writes).toHaveLength(0);
  });
});
