import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { IdentityPage } from "../../pages/IdentityPage";
import type { IdentityBatch, IdentityBatchRequest, IdentityJob, IdentityProfile, IdentityRequest } from "../../../domain/identity";
import { identityApi } from "../../../providers/identity-api";

const visualId = "cyberrealistic-xl-plus-face", realId = "realistic-vision-v5.1-faceid";
const jobId = "identity-0123456789abcdef01234567";
const originalUrl = "/api/identity/jobs/identity-0123456789abcdef01234567/original";
const request: IdentityRequest = { modelId: visualId, referenceId: "ref-a", faceIndex: 0, prompt: "动漫场景", negativePrompt: "", seed: 21,
  width: 768, height: 768, steps: 30, cfg: 5, identityStrength: .8, structureStrength: 0, faceLoraStrength: 0,
  facePolish: true, faceRestoreStrength: 1, animeProfileId: null, animeDenoiseStrength: .45, traceLevel: "off" };
const receipt = { enabled: true, status: "completed", method: "visual-reference-local-redraw", originalImageUrl: originalUrl,
  referenceId: "ref-a", faceIndex: 0, featureKey: "a".repeat(64), faceBox: [20, 30, 120, 130], cropBox: [0, 0, 160, 160],
  denoiseStrength: .45, outsideMaskUnchanged: true, restoreModel: "CyberRealistic XL" };
const makeJob = (options: IdentityRequest = request, polish: unknown = receipt): IdentityJob => ({ id: jobId, state: "complete", progress: 100,
  message: "完成", request: options, result: { imageUrl: "/final.png", metadata: { facePolish: polish as any } }, error: null });
const detailReceipt = { ...receipt, detailerVersion: "masked-face-v1", processingSize: [768, 768],
  detailPrompt: "clean eyes", detailNegativePrompt: "blur" };
let capability: unknown, jobs: IdentityJob[], batches: IdentityBatch[], profile: IdentityProfile;
let posts: Array<{ url: string; body: any }>;
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  localStorage.clear(); capability = { ready: true, message: "视觉参考局部重绘可用" }; jobs = []; batches = []; posts = [];
  profile = { id: "person-a", name: "Example-动漫-视觉", referenceKind: "visual", referenceId: "ref-a", faceIndex: 0,
    state: "ready", defaults: { ...request, facePolish: false }, error: null, createdAt: "2026-10-11", updatedAt: "2026-10-11" };
  // HTTP only: keep real controls, serialization, draft storage and result rendering.
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), body = init?.body ? JSON.parse(String(init.body)) : null;
    if (init?.method === "POST") posts.push({ url, body });
    if (url === "/api/identity/status") return json({ ready: true, modelName: "RV", message: "就绪", loras: [],
      facePolish: { ready: true, message: "真人修脸可用" }, animePolish: { ready: true, message: "动漫档案修脸可用" },
      ...(capability !== undefined ? { visualPolish: capability } : {}), models: [
        { id: realId, name: "RV", architecture: "SD1.5", ready: true, message: "就绪", loras: [] },
        { id: visualId, name: "CyberRealistic XL + Plus Face（动漫视觉参考）", architecture: "SDXL", ready: true, message: "就绪", loras: [] },
        { id: "illustrious-xl-v2.0-plus-face", name: "Illustrious XL + Plus Face", architecture: "SDXL", ready: true, message: "就绪", loras: [] },
      ] });
    if (url === "/api/identity/references") return json([
      { id: "ref-a", name: "当前参考.png", imageUrl: "/reference.png", referenceKind: "visual", faces: [{ index: 0, box: [0, 0, 50, 50] }] },
      { id: "ref-real", name: "真人.png", imageUrl: "/real.png", faces: [{ index: 0, box: [0, 0, 50, 50] }] },
    ]);
    if (url === "/api/identity/profiles") return json([profile]);
    if (url === "/api/identity/profiles/person-a/preset") { profile.defaults = { ...jobs[0].request }; return json(profile); }
    if (url === "/api/identity/profiles/person-a") return json(profile);
    if (url === "/api/identity/jobs") return json(jobs);
    if (url === `/api/identity/jobs/${jobId}`) return json(jobs[0]);
    if (url === "/api/identity/batches" && init?.method === "POST") {
      jobs = [makeJob(body.request, body.request.facePolish ? { ...receipt, denoiseStrength: body.request.animeDenoiseStrength } : { enabled: false, status: "disabled" })];
      const batch: IdentityBatch = { id: "batch-a", request: body as IdentityBatchRequest, state: "complete", items: jobs, totalItems: 1,
        currentItem: 1, completedItems: 1, step: 30, totalSteps: 30, progress: 100, stage: "完成", elapsedMs: 1000, etaMs: null,
        previewUrl: null, error: null, createdAt: "2026-10-11", updatedAt: "2026-10-11" };
      batches = [batch]; return json(batch);
    }
    if (url === "/api/identity/batches") return json(batches);
    if (url === "/api/identity/batches/batch-a") return json(batches[0]);
    throw new Error(`Unexpected HTTP ${url}`);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const checkbox = () => screen.getByRole("checkbox", { name: "生成后修脸（可选）" });
const generate = () => screen.getByRole("button", { name: "生成人物图像" });
async function open(replay?: { id: string; revision: number }) {
  const view = render(<IdentityPage replay={replay} />);
  await waitFor(() => expect(screen.getByLabelText("人物底图模型")).toBeEnabled());
  return view;
}
function prepare() {
  fireEvent.change(screen.getByLabelText("人物底图模型"), { target: { value: visualId } });
  fireEvent.change(screen.getByLabelText("选择参考照"), { target: { value: "ref-a" } });
  fireEvent.change(screen.getByLabelText("场景提示词"), { target: { value: "新的动漫场景" } });
}
async function submit() {
  await waitFor(() => expect(generate()).toBeEnabled()); fireEvent.click(generate());
  await screen.findByRole("status", { name: "批次进度" });
  return posts.find(p => p.url === "/api/identity/batches")!.body.request;
}

it("offers visual polish OFF by default and submits the current reference with default redraw strength after opting in", async () => {
  await open(); prepare();
  expect(checkbox()).toBeEnabled(); expect(checkbox()).not.toBeChecked();
  fireEvent.click(checkbox());
  expect(screen.getByLabelText("重绘强度")).toHaveValue(.35);
  expect(screen.queryByLabelText("面部细节修复强度")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("修脸参考")).not.toBeInTheDocument();
  expect(screen.getByText(/重绘参考：当前参考.png/)).toBeVisible();
  expect(screen.getByRole("option", { name: /H6/ })).toBeEnabled();
  expect(screen.getByRole("option", { name: /H7/ })).toBeEnabled();
  expect(await submit()).toMatchObject({ modelId: visualId, referenceId: "ref-a", faceIndex: 0, facePolish: true, animeProfileId: null, animeDenoiseStrength: .35 });
});

it("retains Illustrious visual model and scheduled reference in profile, draft and submission", async () => {
  profile.defaults = { ...request, modelId: "illustrious-xl-v2.0-plus-face", referenceStart: .2, referenceEnd: .8, traceLevel: "h7" };
  const view = await open();
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-a" } });
  await waitFor(() => expect(screen.getByLabelText("人物底图模型")).toHaveValue("illustrious-xl-v2.0-plus-face"));
  expect(screen.getByLabelText("参考开始比例")).toHaveValue(.2);
  fireEvent.change(screen.getByLabelText("参考结束比例"), { target: { value: ".7" } });
  view.unmount(); await open();
  await waitFor(() => expect(screen.getByLabelText("参考结束比例")).toHaveValue(.7));
  expect(await submit()).toMatchObject({ modelId: "illustrious-xl-v2.0-plus-face", referenceStart: .2, referenceEnd: .7, traceLevel: "h7", researchCoverage: "representative" });
});

it("blocks an invalid reference interval before submission", async () => {
  await open(); prepare();
  fireEvent.change(screen.getByLabelText("参考开始比例"), { target: { value: ".8" } });
  fireEvent.change(screen.getByLabelText("参考结束比例"), { target: { value: ".2" } });
  expect(generate()).toBeDisabled(); expect(posts).toHaveLength(0);
});

it("retains independent detail prompts in drafts and sends them without changing the scene prompt", async () => {
  const view = await open(); prepare(); fireEvent.click(checkbox());
  fireEvent.change(screen.getByLabelText("修脸提示词"), { target: { value: "clean anime eyes" } });
  fireEvent.change(screen.getByLabelText("修脸反向提示词"), { target: { value: "blurry lines" } });
  view.unmount(); await open();
  expect(screen.getByLabelText("修脸提示词")).toHaveValue("clean anime eyes");
  expect(screen.getByLabelText("修脸反向提示词")).toHaveValue("blurry lines");
  fireEvent.change(screen.getByLabelText("选择参考照"), { target: { value: "ref-a" } });
  expect(await submit()).toMatchObject({ visualPolishPrompt: "clean anime eyes", visualPolishNegativePrompt: "blurry lines", prompt: "新的动漫场景" });
});

it.each([
  { detailerVersion: undefined }, { detailerVersion: null }, { detailerVersion: "unknown" },
  { processingSize: [1024, 1024] }, { processingSize: [512, 512] }, { processingSize: [768.5, 768] },
  { processingSize: undefined }, { detailPrompt: "other scene" }, { detailNegativePrompt: "other" },
])("does not label malformed masked-detail evidence completed: %j", async invalid => {
  const params = { ...request, visualPolishPrompt: "clean eyes", visualPolishNegativePrompt: "blur" };
  jobs = [makeJob(params, { ...detailReceipt, ...invalid })];
  const decoded = await identityApi.job(jobId);
  expect(decoded.result?.metadata.facePolishValidationError).toMatch(/无效/);
  expect(decoded.result?.imageUrl).toBe("/final.png");
});

it("reads back a valid masked-detail receipt with its actual processing size", async () => {
  jobs = [makeJob({ ...request, visualPolishPrompt: "clean eyes", visualPolishNegativePrompt: "blur" }, detailReceipt)];
  const decoded = await identityApi.job(jobId);
  expect(decoded.result?.metadata.facePolish).toMatchObject(detailReceipt);
});

it("restores detail prompts from profile presets and old requests use empty automatic defaults", async () => {
  profile.defaults = { ...request, visualPolishPrompt: "precise eyelashes", visualPolishNegativePrompt: "blur" };
  const view = await open();
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-a" } });
  await waitFor(() => expect(screen.getByLabelText("修脸提示词")).toHaveValue("precise eyelashes"));
  jobs = [makeJob()]; view.rerender(<IdentityPage replay={{ id: jobId, revision: 1 }} />);
  await waitFor(() => expect(screen.getByLabelText("修脸提示词")).toHaveValue(""));
});

it.each([.15, .65])("accepts visual redraw strength boundary %s without changing the reference", async strength => {
  await open(); prepare(); fireEvent.click(checkbox());
  fireEvent.change(screen.getByLabelText("重绘强度"), { target: { value: String(strength) } });
  expect(await submit()).toMatchObject({ animeDenoiseStrength: strength, referenceId: "ref-a", animeProfileId: null });
});

it.each(["", ".14", ".66"])("blocks invalid visual redraw strength %j before POST", async strength => {
  await open(); prepare(); fireEvent.click(checkbox());
  fireEvent.change(screen.getByLabelText("重绘强度"), { target: { value: strength } });
  expect(generate()).toBeDisabled(); expect(posts).toHaveLength(0);
});

it.each([undefined, { ready: false, message: "视觉重绘模型未就绪" }])("keeps baseline usable when only real/anime polish capabilities are ready (%j)", async value => {
  capability = value; await open(); prepare();
  expect(checkbox()).toBeDisabled(); expect(checkbox()).not.toBeChecked();
  expect(screen.getByText(value?.message ?? /服务未报告视觉参考局部重绘能力/)).toBeVisible();
  expect(await submit()).toMatchObject({ facePolish: false });
});

it.each([false, true])("preserves explicit visual opt-in and strength in a draft (profile=%s)", async bound => {
  const view = await open();
  if (bound) {
    fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-a" } });
    await waitFor(() => expect(screen.getByLabelText("人物底图模型")).toHaveValue(visualId));
  } else prepare();
  fireEvent.click(checkbox()); fireEvent.change(screen.getByLabelText("重绘强度"), { target: { value: ".55" } });
  view.unmount(); await open();
  await waitFor(() => expect(checkbox()).toBeChecked());
  expect(screen.getByLabelText("重绘强度")).toHaveValue(.55);
  expect(posts).toHaveLength(0);
});

it("restores visual profile presets and historical requests with their explicit strengths", async () => {
  profile.defaults = { ...request, animeDenoiseStrength: .6 };
  jobs = [makeJob()]; const view = await open();
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-a" } });
  await waitFor(() => expect(checkbox()).toBeChecked());
  expect(screen.getByLabelText("重绘强度")).toHaveValue(.6);
  view.rerender(<IdentityPage replay={{ id: jobId, revision: 1 }} />);
  await waitFor(() => expect(screen.getByLabelText("重绘强度")).toHaveValue(.45));
  fireEvent.click(screen.getByRole("button", { name: `将 ${jobId} 存为人物预设` }));
  await waitFor(() => expect(posts.some(p => p.url.endsWith("/preset"))).toBe(true));
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-a" } });
  await waitFor(() => expect(screen.getByLabelText("重绘强度")).toHaveValue(.45));
});

it("clears opt-in in both directions when changing between FaceID and visual", async () => {
  await open(); fireEvent.click(checkbox()); prepare();
  expect(checkbox()).not.toBeChecked(); fireEvent.click(checkbox());
  fireEvent.change(screen.getByLabelText("重绘强度"), { target: { value: ".55" } });
  fireEvent.change(screen.getByLabelText("人物底图模型"), { target: { value: realId } });
  expect(checkbox()).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("人物底图模型"), { target: { value: visualId } });
  expect(checkbox()).not.toBeChecked(); fireEvent.click(checkbox());
  expect(screen.getByLabelText("重绘强度")).toHaveValue(.35);
});

it("preserves unavailable historical opt-in and provides explicit opt-out without implying redraw ran", async () => {
  capability = { ready: false, message: "视觉重绘模型未就绪" }; jobs = [makeJob()];
  await open({ id: jobId, revision: 1 });
  expect(checkbox()).toBeChecked(); expect(checkbox()).toBeDisabled(); expect(generate()).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "关闭局部重绘" }));
  expect(checkbox()).not.toBeChecked(); expect(generate()).toBeEnabled();
});

it("labels visual redraw results and switches to the preserved original", async () => {
  jobs = [makeJob()]; await open({ id: jobId, revision: 1 });
  const result = within(screen.getByRole("region", { name: `原图与重绘结果 ${jobId}` }));
  expect(result.getByText(/局部重绘完成/)).toBeVisible();
  expect(result.getByAltText("重绘结果")).toHaveAttribute("src", expect.stringContaining("/final.png?identityResult="));
  fireEvent.click(result.getByRole("button", { name: "查看生成原图" }));
  expect(result.getByAltText("生成原图")).toHaveAttribute("src", originalUrl);
  fireEvent.click(result.getByRole("button", { name: "查看重绘结果" }));
  expect(result.getByAltText("重绘结果")).toBeVisible();
});

it("keeps the original visible and labels a failed visual redraw honestly", async () => {
  jobs = [makeJob(request, { enabled: true, status: "failed", method: "visual-reference-local-redraw", message: "没有可重绘的人脸", originalImageUrl: originalUrl })];
  await open({ id: jobId, revision: 1 });
  expect(screen.getByText("局部重绘失败，已保留原图")).toBeVisible();
  expect(screen.getByAltText("保留的原图")).toHaveAttribute("src", originalUrl);
});

it.each([null, { ready: "true", message: "bad" }, { ready: true, message: {} }])("decodes malformed visual capability as unavailable (%j)", async value => {
  capability = value;
  const status = await identityApi.status();
  expect(status.visualPolish?.ready).toBe(false);
  expect(status.visualPolish?.message).toMatch(/无效/);
  expect(status.facePolish?.ready).toBe(true);
});

it.each([
  ["reference mismatch", { referenceId: "ref-other" }], ["face mismatch", { faceIndex: 1 }],
  ["wrong method", { method: "face-swap" }], ["bad box", { cropBox: [10, 0, 5, 20] }],
  ["bad strength", { denoiseStrength: .9 }], ["non-boolean mask receipt", { outsideMaskUnchanged: "true" }],
  ["missing feature key", { featureKey: null }], ["invalid restore model", { restoreModel: [] }],
])("rejects an invalid visual completion receipt but keeps the image: %s", async (_label, invalid) => {
  jobs = [makeJob(request, { ...receipt, ...invalid })];
  const job = await identityApi.job(jobId);
  expect(job.result?.imageUrl).toBe("/final.png");
  expect(job.result?.metadata.facePolish?.status).not.toBe("completed");
  expect(job.result?.metadata.facePolishValidationError).toMatch(/无效/);
});

it.each([
  ["changed pixels outside the mask", { outsideMaskUnchanged: false }],
  ["missing original", { originalImageUrl: undefined }],
  ["original belongs to another job", { originalImageUrl: "/api/identity/jobs/identity-aaaaaaaaaaaaaaaaaaaaaaaa/original" }],
  ["noncanonical original path", { originalImageUrl: "/original.png" }],
  ["external original URL", { originalImageUrl: "https://example.com/api/identity/jobs/identity-0123456789abcdef01234567/original" }],
])("does not show a completion badge or original toggle for %s", async (_label, invalid) => {
  jobs = [makeJob(request, { ...receipt, ...invalid })];
  await open({ id: jobId, revision: 1 });
  expect(screen.queryByText(/局部重绘完成/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "查看生成原图" })).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(/视觉重绘记录无效/);
  expect(screen.getByAltText("生成结果")).toHaveAttribute("src", "/final.png");
});
