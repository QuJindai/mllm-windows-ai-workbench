import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// jsdom resolves the cascade by source order, not specificity. Load shared form
// rules first so computed-style assertions exercise the scoped overrides.
import "../shell.css";
import "../workstation.css";
import { App } from "../App";
import { DreamProviderContext } from "../providers";
import { MockDreamProvider } from "../../providers/MockDreamProvider";
import type { HistoryItem } from "../../domain/history";
import type { IdentityBatchRequest, IdentityStatus } from "../../domain/identity";
import { identityApi } from "../../providers/identity-api";
import { IdentityPage } from "./IdentityPage";

const reference = {
  id: "ref-test", name: "测试参考.png", imageUrl: "/api/identity/references/ref-test/image",
  faces: [{ index: 0, box: [10, 20, 90, 110] }, { index: 3, box: [110, 20, 190, 110] }],
};
const singleReference = { ...reference, id: "ref-single", name: "单人参考.png", faces: [reference.faces[0]] };
const request = {
  referenceId: "ref-test", faceIndex: 3, prompt: "窗边肖像", negativePrompt: "模糊",
  seed: 42, width: 512, height: 768, steps: 28, cfg: 5.5,
  identityStrength: 0.8, structureStrength: 1, faceLoraStrength: 0.6,
};
const completeJob = {
  id: "identity-job-1", state: "complete", progress: 100, message: "生成完成", request,
  result: { imageUrl: "/api/outputs/identity-job-1.png", metadata: { seed: 42, stages: { samplingSeconds: 12.3 }, peakVramMb: 4100 } },
  error: null,
};
type TestJob = Omit<typeof completeJob, "state" | "result" | "error"> & {
  resultDeleted?: boolean;
  state: string; result: { imageUrl: string; metadata: Record<string, unknown> } | null; error: string | null;
};
let runtime: IdentityStatus = { ready: true, modelName: "Realistic Vision V5.1", message: "运行环境就绪", loras: [{ id: "style-sd15", name: "胶片风格" }] };
let references = [reference, singleReference];
let jobs: TestJob[] = [];
let nextJob: TestJob;
let batchRequest: IdentityBatchRequest | null;
function batchResponse() {
  const item = jobs.find((value) => value.id === nextJob.id) ?? nextJob;
  return { id: "batch-test", state: item.state, request: batchRequest ?? { request: item.request, count: 1, previewEvery: 0 },
    items: [item], currentItem: 1, totalItems: 1, completedItems: item.state === "complete" ? 1 : 0,
    step: 0, totalSteps: 28, progress: item.progress, stage: item.message, elapsedMs: 0, etaMs: null,
    previewUrl: null, error: item.error, createdAt: "2026-09-20", updatedAt: "2026-09-20" };
}
let uploadStatus = 200;
let generateStatus = 200;
let fetchCalls: Array<{ url: string; method: string; body: unknown }>;
let fetchOverride: ((url: string, init?: RequestInit) => Promise<Response> | undefined) | undefined;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  localStorage.clear();
  runtime = { ready: true, modelName: "Realistic Vision V5.1", message: "运行环境就绪", loras: [{ id: "style-sd15", name: "胶片风格" }] };
  references = [reference, singleReference];
  jobs = [];
  batchRequest = null;
  nextJob = { ...completeJob, state: "queued", progress: 0, message: "等待执行", result: null };
  uploadStatus = 200;
  generateStatus = 200;
  fetchCalls = [];
  fetchOverride = undefined;
  // Only the HTTP boundary is replaced. App, IdentityPage, FileReader and the API adapter are real.
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    fetchCalls.push({ url, method, body });
    const overridden = fetchOverride?.(url, init);
    if (overridden) return overridden;
    if (url === "/api/identity/status") return json(runtime);
    if (url === "/api/identity/references" && method === "GET") return json(references);
    if (url === "/api/identity/references" && method === "POST") return uploadStatus === 200 ? json(reference) : json({ detail: "没有检测到人脸" }, uploadStatus);
    if (url === "/api/identity/profiles") return json([]);
    if (url === "/api/identity/batches" && method === "GET") return json(batchRequest ? [batchResponse()] : []);
    if (url === "/api/identity/batches" && method === "POST") {
      if (generateStatus !== 200) return json({ detail: [{ loc: ["body", "steps"], msg: "步数超出范围", type: "value_error" }] }, generateStatus);
      batchRequest = body;
      nextJob = { ...nextJob, request: body.request };
      jobs = [nextJob, ...jobs.filter((job) => job.id !== nextJob.id)];
      return json(batchResponse());
    }
    if (url === "/api/identity/generate") return json(completeJob);
    if (url === "/api/identity/jobs") return json(jobs);
    if (url.endsWith("/cancel") && method === "POST") {
      nextJob = { ...nextJob, state: "cancelled", message: "用户取消" };
      jobs = [nextJob];
      return json(url.includes("/batches/") ? batchResponse() : nextJob);
    }
    if (url === "/api/identity/batches/batch-test") return json(batchResponse());
    if (url.startsWith("/api/identity/jobs/")) {
      const job = jobs.find((value) => value.id === decodeURIComponent(url.split("/").at(-1)!));
      return job ? json(job) : json({ detail: "任务不存在" }, 404);
    }
    throw new Error(`Unexpected fetch: ${method} ${url}`);
  }));
});

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it.each([false, true])("deletes a person result without removing its reference (batch=%s)", async (isBatch) => {
  nextJob = { ...completeJob }; jobs = [nextJob];
  if (isBatch) {
    batchRequest = { request: { ...request, facePolish: false, faceRestoreStrength: 1 }, count: 1, previewEvery: 0 };
    localStorage.setItem("dream.identity.last-batch.v1", "batch-test");
  } else localStorage.setItem("dream.identity.last-job.v1", nextJob.id);
  fetchOverride = (url, init) => url === `/api/history/${nextJob.id}` && init?.method === "DELETE"
    ? Promise.resolve(json({ deleted: nextJob.id })) : undefined;
  render(<IdentityPage />);
  await screen.findByAltText("生成结果");
  fireEvent.click(screen.getByRole("button", { name: `删除图片 ${nextJob.id}` }));
  expect(screen.getByRole("dialog", { name: "删除生成图片" })).toHaveTextContent("不删除人物档案和参考照片");
  fireEvent.click(screen.getByRole("button", { name: "确认删除图片" }));
  await waitFor(() => expect(screen.queryByAltText("生成结果")).not.toBeInTheDocument());
  expect(screen.getByAltText("任务参考照")).toBeInTheDocument();
  expect(fetchCalls.filter(call => call.method === "DELETE")).toEqual([{ url: `/api/history/${nextJob.id}`, method: "DELETE", body: undefined }]);
});

it("does not resurrect a deleted person result when reopening a stored task", async () => {
  nextJob = { ...completeJob, resultDeleted: true }; jobs = [nextJob];
  localStorage.setItem("dream.identity.last-job.v1", nextJob.id);
  render(<IdentityPage />);
  await screen.findByText(/图片已删除/);
  expect(screen.queryByAltText("生成结果")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: `删除图片 ${nextJob.id}` })).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "场景提示词" })).toHaveValue(request.prompt);
});

async function openWorkspace(provider = new MockDreamProvider(), strict = false) {
  const app = <DreamProviderContext.Provider value={provider}><App /></DreamProviderContext.Provider>;
  const view = render(strict ? <StrictMode>{app}</StrictMode> : app);
  fireEvent.click(screen.getByRole("button", { name: "人物创作" }));
  const page = await screen.findByRole("region", { name: "人物创作工作区" });
  await within(page).findByText(/Realistic Vision|Illustrious XL/, { selector: ".identity-runtime strong" });
  return { ...view, page, ui: within(page) };
}

async function prepare(ui: ReturnType<typeof within>, id = "ref-test") {
  await waitFor(() => expect(ui.getByRole("option", { name: "测试参考.png" })).toBeInTheDocument());
  fireEvent.change(ui.getByLabelText("选择参考照"), { target: { value: id } });
  if (id === "ref-test") fireEvent.click(ui.getByRole("radio", { name: "人脸 4" }));
  fireEvent.change(ui.getByLabelText("场景提示词"), { target: { value: "窗边肖像" } });
}
function posts(path: string) { return fetchCalls.filter((call) => call.method === "POST" && call.url === path); }

describe("人物创作 HTTP workspace", () => {
  function twoModels(ready = true) {
    runtime.models = [
      { id: "realistic-vision-v5.1-faceid", name: "Realistic Vision V5.1 + FaceID Plus V2", architecture: "SD1.5", ready: true, message: "就绪", loras: runtime.loras },
      { id: "illustrious-xl-v2.0-faceid", name: "Illustrious XL v2.0 + FaceID Plus V2 SDXL", architecture: "SDXL", ready, message: ready ? "就绪" : "缺少配套文件", loras: [] },
    ];
  }
  it("selects Illustrious with compatible defaults and sends model identity to the batch", async () => {
    twoModels();
    const { ui } = await openWorkspace();
    await prepare(ui, "ref-single");
    fireEvent.change(ui.getByLabelText("可选 LoRA"), { target: { value: "style-sd15" } });
    fireEvent.change(ui.getByLabelText("人物底图模型"), { target: { value: "illustrious-xl-v2.0-faceid" } });
    expect(ui.getByLabelText("宽度")).toHaveValue(768);
    expect(ui.getByLabelText("步数")).toHaveValue(30);
    expect(ui.getByLabelText("可选 LoRA")).toHaveValue("");
    expect(ui.queryByRole("option", { name: "胶片风格" })).not.toBeInTheDocument();
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    await waitFor(() => expect(batchRequest?.request).toMatchObject({ modelId: "illustrious-xl-v2.0-faceid", width: 768, height: 768, steps: 30, cfg: 5 }));
  });
  it("keeps unavailable Illustrious visibly unavailable without submitting RV", async () => {
    twoModels(false);
    const { ui } = await openWorkspace();
    await prepare(ui, "ref-single");
    fireEvent.change(ui.getByLabelText("人物底图模型"), { target: { value: "illustrious-xl-v2.0-faceid" } });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    expect(ui.getByText("缺少配套文件")).toBeVisible();
  });
  it("restores Illustrious historical parameters without replacing them with selection defaults", async () => {
    twoModels();
    nextJob = { ...completeJob, request: { ...request, modelId: "illustrious-xl-v2.0-faceid", width: 640, steps: 19 } } as TestJob;
    jobs = [nextJob]; localStorage.setItem("dream.identity.last-job.v1", nextJob.id);
    const { ui } = await openWorkspace();
    await waitFor(() => expect(ui.getByLabelText("人物底图模型")).toHaveValue("illustrious-xl-v2.0-faceid"));
    expect(ui.getByLabelText("宽度")).toHaveValue(640);
    expect(ui.getByLabelText("步数")).toHaveValue(19);
    fireEvent.change(ui.getByLabelText("人物显微镜采集"), { target: { value: "h7" } });
    expect(ui.getByRole("option", { name: /扩展采集/ })).toBeDisabled();
  });
  it.each([false, true])("shows research publication failure outside collapsed metadata (batch=%s)", async (batch) => {
    nextJob = { ...completeJob, result: { ...completeJob.result, metadata: { research: { status:"failed", h6:false, h7:false } } } };
    jobs = [nextJob];
    if (batch) {
      batchRequest = {request: {...request, facePolish:false, faceRestoreStrength:1}, count:1, previewEvery:0};
      localStorage.setItem("dream.identity.last-batch.v1", "batch-test");
    } else localStorage.setItem("dream.identity.last-job.v1", nextJob.id);
    const {ui} = await openWorkspace();
    expect(await ui.findByText("研究采集失败，图片已保留")).toBeVisible();
    expect(ui.queryByRole("link", {name:"在显微镜打开此任务"})).not.toBeInTheDocument();
  });
  it("opts into bounded microscope capture without changing identity strengths", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui, "ref-single");
    expect(ui.getByLabelText("人物显微镜采集")).toHaveValue("off");
    fireEvent.change(ui.getByLabelText("人物显微镜采集"), { target: { value: "h7" } });
    fireEvent.change(ui.getByLabelText("研究采集范围"), { target: { value: "extended" } });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    fireEvent.change(ui.getByLabelText("高度"), { target: { value: "512" } });
    fireEvent.change(ui.getByLabelText("步数"), { target: { value: "12" } });
    fireEvent.change(ui.getByLabelText("场景提示词"), { target: { value: "portrait ".repeat(150) } });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    fireEvent.change(ui.getByLabelText("步数"), { target: { value: "8" } });
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    await ui.findByRole("button", { name: "取消批次" });
    expect(posts("/api/identity/batches")[0].body).toMatchObject({ request: {
      traceLevel: "h7", researchCoverage: "extended", width:512, height:512, steps:8,
      identityStrength:.82, structureStrength:.9, faceLoraStrength:.55, facePolish:false,
    } });
  });
  it("keeps the old single-generate request and job response compatible", async () => {
    const value = await identityApi.generate({ ...request, facePolish: false, faceRestoreStrength: 1 });
    expect(value).toEqual(completeJob);
    expect(fetchCalls).toEqual([{ url: "/api/identity/generate", method: "POST", body: { ...request, facePolish: false, faceRestoreStrength: 1 } }]);
  });

  it("restores a legacy saved job and cancels only through the legacy job endpoint", async () => {
    jobs = [nextJob];
    localStorage.setItem("dream.identity.last-job.v1", nextJob.id);
    const { ui } = await openWorkspace();
    fireEvent.click(await ui.findByRole("button", { name: "取消人物任务" }));
    await waitFor(() => expect(ui.getByLabelText("当前任务状态")).toHaveTextContent("已取消"));
    expect(posts("/api/identity/jobs/identity-job-1/cancel")).toHaveLength(1);
    expect(posts("/api/identity/batches")).toHaveLength(0);
  });
  it("blocks submission when the runtime is unavailable and lets the user retry readiness", async () => {
    runtime = { ...runtime, ready: false, message: "缺少 FaceID 适配器" };
    const { ui } = await openWorkspace();
    await prepare(ui);
    expect(ui.getByText("缺少 FaceID 适配器")).toBeVisible();
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    runtime = { ...runtime, ready: true, message: "运行环境就绪" };
    fireEvent.click(ui.getByRole("button", { name: "刷新运行状态" }));
    await waitFor(() => expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled());
    expect(posts("/api/identity/batches")).toHaveLength(0);
  });

  it("uploads at the fetch boundary and requires explicit multi-face selection", async () => {
    references = [];
    const { ui } = await openWorkspace();
    fireEvent.change(ui.getByLabelText("上传参考照"), { target: { files: [new File(["synthetic-image"], "测试参考.png", { type: "image/png" })] } });
    await ui.findByRole("radio", { name: "人脸 4" });
    fireEvent.change(ui.getByLabelText("场景提示词"), { target: { value: "窗边肖像" } });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    expect(ui.getByRole("radio", { name: "人脸 1" })).not.toBeChecked();
    fireEvent.click(ui.getByRole("radio", { name: "人脸 4" }));
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled();
    expect(posts("/api/identity/references")[0].body).toEqual({ name: "测试参考.png", imageBase64: "c3ludGhldGljLWltYWdl" });
    expect(JSON.stringify(localStorage)).not.toMatch(/synthetic-image|c3ludGhldGlj|imageBase64|data:image|embedding/);
  });

  it("shows upload errors and does not silently retain the previous person", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui, "ref-single");
    uploadStatus = 422;
    fireEvent.change(ui.getByLabelText("上传参考照"), { target: { files: [new File(["invalid"], "bad.png", { type: "image/png" })] } });
    expect(await ui.findByRole("alert")).toHaveTextContent("没有检测到人脸");
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
  });

  it("submits the exact defaults and optional LoRA without duplicate POSTs", async () => {
    const { ui } = await openWorkspace(undefined, true);
    await prepare(ui);
    fireEvent.change(ui.getByLabelText("反向提示词"), { target: { value: "模糊" } });
    fireEvent.change(ui.getByLabelText("身份强度"), { target: { value: "0.85" } });
    fireEvent.change(ui.getByLabelText("结构强度"), { target: { value: "1.1" } });
    fireEvent.change(ui.getByLabelText("FaceID 配套 LoRA 强度"), { target: { value: "0.65" } });
    fireEvent.change(ui.getByLabelText("可选 LoRA"), { target: { value: "style-sd15" } });
    fireEvent.change(ui.getByLabelText("可选 LoRA 强度"), { target: { value: "0.4" } });
    expect(ui.getAllByRole<HTMLInputElement>("spinbutton").filter((input) => !input.checkValidity()).map((input) => input.closest("label")?.textContent)).toEqual([]);
    const generate = ui.getByRole("button", { name: "生成人物图像" });
    fireEvent.click(generate);
    fireEvent.click(generate);
    await ui.findByRole("button", { name: "取消批次" });
    expect(posts("/api/identity/batches")).toHaveLength(1);
    expect((posts("/api/identity/batches")[0].body as IdentityBatchRequest).request).toEqual({
      modelId: "realistic-vision-v5.1-faceid",
      referenceId: "ref-test", faceIndex: 3, prompt: "窗边肖像", negativePrompt: "模糊",
      seed: "random", width: 512, height: 768, steps: 28, cfg: 5.5,
      identityStrength: 0.85, structureStrength: 1.1, faceLoraStrength: 0.65,
      loraId: "style-sd15", loraStrength: 0.4,
      facePolish: false, faceRestoreStrength: 1,
    });
    expect(ui.getByLabelText("场景提示词")).toBeDisabled();
  });

  it("omits an unselected LoRA, validates seed input and resets face choice on reference changes", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui);
    fireEvent.change(ui.getByLabelText("选择参考照"), { target: { value: "ref-single" } });
    fireEvent.change(ui.getByLabelText("选择参考照"), { target: { value: "ref-test" } });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    fireEvent.click(ui.getByRole("radio", { name: "人脸 1" }));
    fireEvent.change(ui.getByLabelText("种子"), { target: { value: "invalid" } });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    fireEvent.change(ui.getByLabelText("种子"), { target: { value: "123" } });
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    await ui.findByRole("button", { name: "取消批次" });
    expect((posts("/api/identity/batches")[0].body as IdentityBatchRequest).request).toMatchObject({ faceIndex: 0, seed: 123, identityStrength: 0.82, structureStrength: 0.9, faceLoraStrength: 0.55 });
    expect((posts("/api/identity/batches")[0].body as IdentityBatchRequest).request).not.toHaveProperty("loraId");
    expect((posts("/api/identity/batches")[0].body as IdentityBatchRequest).request).not.toHaveProperty("loraStrength");
  });

  it("surfaces validation errors and permits correcting and submitting again", async () => {
    generateStatus = 422;
    const { ui } = await openWorkspace();
    await prepare(ui);
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    expect(await ui.findByRole("alert")).toHaveTextContent("步数超出范围");
    expect(ui.getByLabelText("场景提示词")).toBeEnabled();
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled();
  });

  it("shows the server summary and nested field validation errors instead of a generic 422", async () => {
    fetchOverride = (url, init) => url === "/api/identity/batches" && init?.method === "POST" ? Promise.resolve(json({
      code: "REQUEST_INVALID", message: "人物请求参数无效，请检查参考图、人脸选择和生成参数", retryable: false,
      detail: { errors: [{ loc: ["body", "faceIndex"], type: "value_error", msg: "此字段缺失或不符合参数要求" }] },
    }, 422)) : undefined;
    const { ui } = await openWorkspace();
    await prepare(ui);
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    const alert = await ui.findByRole("alert");
    expect(alert).toHaveTextContent("人物请求参数无效，请检查参考图、人脸选择和生成参数");
    expect(alert).toHaveTextContent("此字段缺失或不符合参数要求");
    expect(alert).not.toHaveTextContent("HTTP 422");
  });

  it("replaces a deleted result image with an explicit message and resets for another job", async () => {
    jobs = [{ ...completeJob }, { ...completeJob, id: "identity-job-2", result: { ...completeJob.result, imageUrl: "/api/outputs/identity-job-2.png" } }];
    const { ui } = await openWorkspace();
    fireEvent.click(await ui.findByRole("button", { name: "打开人物任务 identity-job-1" }));
    fireEvent.error(await ui.findByRole("img", { name: "生成结果" }));
    expect(await ui.findByText("结果文件已删除或不可用")).toBeVisible();
    expect(ui.queryByRole("img", { name: "生成结果" })).not.toBeInTheDocument();
    expect(ui.queryByRole("link", { name: "生成结果" })).not.toBeInTheDocument();
    fireEvent.click(ui.getByRole("button", { name: "打开人物任务 identity-job-2" }));
    expect(await ui.findByRole("img", { name: "生成结果" })).toHaveAttribute("src", "/api/outputs/identity-job-2.png");
    expect(ui.queryByText("结果文件已删除或不可用")).not.toBeInTheDocument();
  });

  it("keeps the same page and active job across navigation, then cancels explicitly", async () => {
    const { ui, page } = await openWorkspace();
    await prepare(ui);
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    await ui.findByRole("button", { name: "取消批次" });
    fireEvent.click(screen.getByRole("button", { name: "历史" }));
    expect(page).toBeInTheDocument();
    expect(page).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "人物创作" }));
    expect(screen.getByRole("region", { name: "人物创作工作区" })).toBe(page);
    expect(ui.getByLabelText("场景提示词")).toHaveValue("窗边肖像");
    expect(posts("/api/identity/batches")).toHaveLength(1);
    expect(fetchCalls.filter((call) => call.url.endsWith("/cancel"))).toHaveLength(0);
    fireEvent.click(ui.getByRole("button", { name: "取消批次" }));
    await waitFor(() => expect(ui.getByLabelText("批次进度")).toHaveTextContent("已取消"));
    expect(posts("/api/identity/batches/batch-test/cancel")).toHaveLength(1);
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled();
  });

  it("restores the last job after refresh with its real result and actual seed, without submitting", async () => {
    nextJob = { ...completeJob };
    const first = await openWorkspace();
    await prepare(first.ui);
    fireEvent.click(first.ui.getByRole("button", { name: "生成人物图像" }));
    expect(await first.ui.findByRole("img", { name: "生成结果" })).toHaveAttribute("src", "/api/outputs/identity-job-1.png");
    first.unmount();
    const restored = await openWorkspace();
    expect(await restored.ui.findByRole("img", { name: "生成结果" })).toHaveAttribute("src", "/api/outputs/identity-job-1.png");
    expect(restored.ui.getByLabelText("种子")).toHaveValue("42");
    fireEvent.click(restored.ui.getByText("查看实测过程"));
    expect(restored.ui.getByText(/H6.*未采集/)).toBeVisible();
    expect(restored.ui.getByText(/H7.*未采集/)).toBeVisible();
    fireEvent.click(restored.ui.getByText("实际任务元数据"));
    expect(restored.ui.getByText(/samplingSeconds/)).toHaveTextContent("12.3");
    expect(posts("/api/identity/batches")).toHaveLength(1);
    expect(fetchCalls.some((call) => call.method === "GET" && call.url === "/api/identity/batches/batch-test")).toBe(true);
  });

  it("restores unsent prompt drafts without storing reference images", async () => {
    const first = await openWorkspace();
    await prepare(first.ui);
    fireEvent.change(first.ui.getByLabelText("反向提示词"), { target: { value: "不要模糊" } });
    first.unmount();
    const restored = await openWorkspace();
    expect(restored.ui.getByLabelText("场景提示词")).toHaveValue("窗边肖像");
    expect(restored.ui.getByLabelText("反向提示词")).toHaveValue("不要模糊");
    expect(restored.ui.getByLabelText("选择参考照")).toHaveValue("");
    expect(posts("/api/identity/batches")).toHaveLength(0);
    expect(JSON.stringify(localStorage)).not.toMatch(/imageUrl|imageBase64|data:image|embedding/);
  });

  it("restores the complete unsent parameter draft over a completed batch, but explicit replay uses frozen parameters", async () => {
    nextJob = { ...completeJob };
    const first = await openWorkspace();
    await prepare(first.ui);
    fireEvent.click(first.ui.getByRole("button", { name: "生成人物图像" }));
    await first.ui.findByRole("img", { name: "生成结果" });
    for (const [label, value] of [["步数", "24"], ["生成张数", "3"], ["中间预览频率", "5"], ["CFG", "7"], ["种子", "12345"], ["宽度", "640"], ["身份强度", "1.1"], ["可选 LoRA", "style-sd15"], ["人物显微镜采集", "basic"]]) {
      fireEvent.change(first.ui.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(first.ui.getByRole("checkbox", { name: "20 步" }));
    first.unmount();
    const restored = await openWorkspace();
    await restored.ui.findByRole("img", { name: "生成结果" });
    for (const [label, value] of [["步数", 24], ["生成张数", 3], ["CFG", 7], ["宽度", 640], ["身份强度", 1.1]] as const) {
      expect(restored.ui.getByLabelText(label), label).toHaveValue(value);
    }
    expect(restored.ui.getByLabelText("种子")).toHaveValue("12345");
    expect(restored.ui.getByLabelText("中间预览频率")).toHaveValue("5");
    expect(restored.ui.getByLabelText("可选 LoRA")).toHaveValue("style-sd15");
    expect(restored.ui.getByLabelText("人物显微镜采集")).toHaveValue("basic");
    expect(restored.ui.getByRole("checkbox", { name: "20 步" })).toBeChecked();
    fireEvent.click(restored.ui.getByRole("button", { name: "打开人物批次 batch-test" }));
    await waitFor(() => expect(restored.ui.getByLabelText("步数")).toHaveValue(batchRequest!.request.steps));
    expect(restored.ui.getByLabelText("生成张数")).toHaveValue(1);
    expect(restored.ui.getByLabelText("种子")).toHaveValue("42");
    expect(restored.ui.getByRole("checkbox", { name: "20 步" })).not.toBeChecked();
    expect(posts("/api/identity/batches")).toHaveLength(1);
  });

  it("restores unsent numeric and batch drafts even before a first job and preserves invalid empty inputs", async () => {
    const first = await openWorkspace();
    fireEvent.change(first.ui.getByLabelText("步数"), { target: { value: "24" } });
    fireEvent.change(first.ui.getByLabelText("生成张数"), { target: { value: "3" } });
    fireEvent.change(first.ui.getByLabelText("种子"), { target: { value: "invalid-draft" } });
    fireEvent.change(first.ui.getByLabelText("CFG"), { target: { value: "" } });
    first.unmount();
    const restored = await openWorkspace();
    expect(restored.ui.getByLabelText("步数")).toHaveValue(24);
    expect(restored.ui.getByLabelText("生成张数")).toHaveValue(3);
    expect(restored.ui.getByLabelText("种子")).toHaveValue("invalid-draft");
    expect(restored.ui.getByLabelText("CFG")).toHaveValue(null);
    expect(restored.ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    expect(posts("/api/identity/batches")).toHaveLength(0);
  });

  it("polls a running job to failure and leaves its error visible", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui);
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    await ui.findByRole("button", { name: "取消批次" });
    jobs = [{ ...nextJob, state: "failed", error: "CUDA 显存不足", message: "运行失败" }];
    await waitFor(() => expect(ui.getByLabelText("批次进度")).toHaveTextContent("失败"), { timeout: 3500 });
    expect(ui.getByRole("alert")).toHaveTextContent("CUDA 显存不足");
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled();
  });

  it("fetches an identity history item by id and supports replaying the same item again", async () => {
    jobs = [{ ...completeJob }];
    class IdentityHistoryProvider extends MockDreamProvider {
      override async listHistory(query: Parameters<MockDreamProvider["listHistory"]>[0]) {
        const item: HistoryItem = {
          id: "identity-job-1", title: "人物历史", prompt: "普通历史字段不能替代完整人物参数", negativePrompt: "",
          modelId: "realistic-vision-v5.1-faceid", modelName: "Realistic Vision V5.1", width: 512, height: 768,
          steps: 28, cfg: 5.5, seed: 42, generationTimeMs: 12300, createdAt: "2026-09-20T00:00:00Z",
          imageUrl: completeJob.result.imageUrl, filePath: "E:/Dream/outputs/test.png", tags: [], favorite: false, status: "complete", truth: "observed",
        };
        return { items: [item], total: 1, page: query.page, pageSize: query.pageSize };
      }
    }
    const provider = new IdentityHistoryProvider();
    const normalGenerate = vi.spyOn(provider, "generate");
    render(<DreamProviderContext.Provider value={provider}><App /></DreamProviderContext.Provider>);
    for (let index = 0; index < 2; index += 1) {
      fireEvent.click(screen.getByRole("button", { name: "历史" }));
      fireEvent.click(await screen.findByRole("button", { name: "重新生成此图" }));
      expect(await screen.findByRole("heading", { name: "人物创作", level: 1 })).toBeVisible();
      await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("窗边肖像"));
      expect(screen.getByLabelText("身份强度")).toHaveValue(0.8);
      expect(screen.getByRole("radio", { name: "人脸 4" })).toBeChecked();
      fireEvent.change(screen.getByLabelText("场景提示词"), { target: { value: "未提交修改" } });
    }
    expect(fetchCalls.filter((call) => call.url === "/api/identity/jobs/identity-job-1")).toHaveLength(2);
    expect(posts("/api/identity/batches")).toHaveLength(0);
    expect(normalGenerate).not.toHaveBeenCalled();
  });

  it("does not let an older delayed history request overwrite the latest selection", async () => {
    jobs = [{ ...completeJob }, { ...completeJob, id: "identity-job-2", request: { ...request, prompt: "第二个任务" } }];
    let release!: (response: Response) => void;
    fetchOverride = (url) => url === "/api/identity/jobs/identity-job-1" ? new Promise<Response>((resolve) => { release = resolve; }) : undefined;
    const { ui } = await openWorkspace();
    fireEvent.click(await ui.findByRole("button", { name: /打开人物任务 identity-job-1/ }));
    fireEvent.click(ui.getByRole("button", { name: /打开人物任务 identity-job-2/ }));
    await waitFor(() => expect(ui.getByLabelText("场景提示词")).toHaveValue("第二个任务"));
    await act(async () => { release(json(completeJob)); });
    expect(ui.getByLabelText("场景提示词")).toHaveValue("第二个任务");
  });

  it("restores frozen running parameters instead of overlaying an unrelated text draft", async () => {
    const first = await openWorkspace();
    await prepare(first.ui);
    fireEvent.click(first.ui.getByRole("button", { name: "生成人物图像" }));
    await first.ui.findByRole("button", { name: "取消批次" });
    first.unmount();
    localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "另一个标签页的草稿", negativePrompt: "其他草稿",
      polishContext: "batch:batch-test", parameters: { steps: 24, seed: "999" }, batchSettings: { count: 3, previewEvery: 5 } }));
    const { ui } = await openWorkspace();
    await ui.findByRole("button", { name: "取消批次" });
    expect(ui.getByLabelText("场景提示词")).toHaveValue("窗边肖像");
    expect(ui.getByLabelText("场景提示词")).toBeDisabled();
    expect(ui.getByLabelText("步数")).toHaveValue(28);
    expect(ui.getByLabelText("生成张数")).toHaveValue(1);
    expect(ui.getByLabelText("种子")).toHaveValue("random");
    expect(posts("/api/identity/batches")).toHaveLength(1);
  });

  it("rejects values outside the identity service bounds before sending a request", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui);
    const invalidValues = [
      ["宽度", "255", "512"], ["宽度", "513", "512"], ["高度", "776", "768"],
      ["步数", "51", "28"], ["CFG", "1", "5.5"], ["CFG", "16", "5.5"],
      ["身份强度", "1.6", "0.82"], ["结构强度", "-0.1", "0.9"],
      ["FaceID 配套 LoRA 强度", "2", "0.55"], ["种子", "2147483648", "random"],
    ];
    for (const [label, invalid, valid] of invalidValues) {
      fireEvent.change(ui.getByLabelText(label), { target: { value: invalid } });
      expect(ui.getByRole("button", { name: "生成人物图像" }), label).toBeDisabled();
      fireEvent.change(ui.getByLabelText(label), { target: { value: valid } });
    }
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled();
    expect(posts("/api/identity/batches")).toHaveLength(0);
  });

  it("renders returned observed stage times and GPU memory while keeping missing measurements unavailable", async () => {
    jobs = [{ ...completeJob, result: { imageUrl: completeJob.result.imageUrl, metadata: {
      seed: 42, stages: [{ name: "采样与 VAE 解码", durationMs: 12300, truth: "observed" }], peakAllocatedMiB: 3100,
      generation_time_ms: 19800, peakReservedMiB: 3379, cacheHit: true,
    } } }];
    const { ui } = await openWorkspace();
    fireEvent.click(await ui.findByRole("button", { name: /打开人物任务 identity-job-1/ }));
    const measurements = await ui.findByRole("table", { name: "实测阶段耗时" });
    expect(within(measurements).getByText("采样与 VAE 解码")).toBeVisible();
    expect(within(measurements).getByText("12.30 秒")).toBeVisible();
    expect(ui.getByText("峰值已分配显存：3100 MiB")).toBeVisible();
    expect(ui.getByText("峰值保留显存：3379 MiB")).toBeVisible();
    expect(ui.getByText("推理阶段合计：19.80 秒（不含工作进程启动）")).toBeVisible();
    expect(ui.getByText("特征缓存：命中")).toBeVisible();
  });

  it("explains local processing and research-only noncommercial weight licensing", async () => {
    const { ui } = await openWorkspace();
    expect(ui.getByText(/本地处理：/)).toHaveTextContent("当前本机 Dream 服务");
    expect(ui.getByText(/本地处理：/)).toHaveTextContent("浏览器仅保存生成参数草稿");
    expect(ui.getByText(/模型许可：/)).toHaveTextContent("FaceID / InsightFace");
    expect(ui.getByText(/模型许可：/)).toHaveTextContent("研究/非商业");
    expect(ui.getByText(/模型许可：/)).toHaveTextContent("尚未确认商业使用授权");
  });

  it("keeps a replay selected when an earlier generation POST returns late", async () => {
    jobs = [{ ...completeJob, id: "older-job", request: { ...request, prompt: "历史选中的任务" } }];
    let release!: (response: Response) => void;
    fetchOverride = (url, init) => url === "/api/identity/batches" && init?.method === "POST" ? new Promise<Response>((resolve) => { release = resolve; }) : undefined;
    const view = render(<IdentityPage />);
    const ui = within(screen.getByRole("region", { name: "人物创作工作区" }));
    await ui.findByText("Realistic Vision V5.1");
    await prepare(ui);
    fireEvent.click(ui.getByRole("button", { name: "生成人物图像" }));
    await waitFor(() => expect(release).toBeTypeOf("function"));
    view.rerender(<IdentityPage replay={{ id: "older-job", revision: 1 }} />);
    await waitFor(() => expect(ui.getByLabelText("场景提示词")).toHaveValue("历史选中的任务"));
    await act(async () => { release(json(batchResponse())); });
    expect(ui.getByLabelText("当前任务状态")).toHaveTextContent("完成");
    expect(ui.getByRole("button", { name: "打开人物任务 older-job" })).toHaveAttribute("aria-pressed", "true");
    expect(ui.getByRole("button", { name: "打开人物任务 identity-job-1" })).toBeInTheDocument();
  });

  it("keeps the replay reference when an earlier upload finishes late", async () => {
    jobs = [{ ...completeJob, request: { ...request, referenceId: "ref-single", faceIndex: 0 } }];
    let release!: (response: Response) => void;
    fetchOverride = (url, init) => url === "/api/identity/references" && init?.method === "POST"
      ? new Promise<Response>((resolve) => { release = resolve; }) : undefined;
    const view = render(<IdentityPage />);
    const ui = within(screen.getByRole("region", { name: "人物创作工作区" }));
    await ui.findByText("Realistic Vision V5.1");
    fireEvent.change(ui.getByLabelText("上传参考照"), { target: { files: [new File(["synthetic-image"], "new.png", { type: "image/png" })] } });
    await waitFor(() => expect(release).toBeTypeOf("function"));
    view.rerender(<IdentityPage replay={{ id: "identity-job-1", revision: 1 }} />);
    await waitFor(() => expect(ui.getByLabelText("选择参考照")).toHaveValue("ref-single"));
    await act(async () => { release(json(reference)); });
    expect(ui.getByLabelText("选择参考照")).toHaveValue("ref-single");
    expect(ui.getByRole("radio", { name: "人脸 1" })).toBeChecked();
  });

  it("locks writes until refreshed runtime and reference data have arrived", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui);
    let release!: (response: Response) => void;
    fetchOverride = (url) => url === "/api/identity/status" ? new Promise<Response>((resolve) => { release = resolve; }) : undefined;
    fireEvent.click(ui.getByRole("button", { name: "刷新运行状态" }));
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    expect(ui.getByLabelText("上传参考照")).toBeDisabled();
    await act(async () => { release(json(runtime)); });
    expect(ui.getByRole("button", { name: "生成人物图像" })).toBeEnabled();
  });

  it("keeps face radios compact and horizontal under the workstation styles", async () => {
    const { ui } = await openWorkspace();
    await prepare(ui, "ref-single");
    const radio = ui.getByRole("radio", { name: "人脸 1" });
    const radioStyle = window.getComputedStyle(radio);
    expect(radioStyle.width).toBe("18px");
    expect(radioStyle.height).toBe("18px");
    expect(radioStyle.minHeight).toBe("18px");
    expect(radioStyle.flexShrink).toBe("0");
    const labelStyle = window.getComputedStyle(radio.closest("label")!);
    expect(labelStyle.display).toBe("inline-flex");
    expect(labelStyle.flexDirection).toBe("row");
    expect(labelStyle.flexWrap).toBe("nowrap");
    expect(labelStyle.whiteSpace).toBe("nowrap");
    expect(window.getComputedStyle(ui.getByRole("button", { name: "生成人物图像" })).color).toBe("rgb(255, 255, 255)");
    expect(window.getComputedStyle(ui.getByRole("img", { name: "参考照" })).maxHeight).toBe("240px");
  });
});
