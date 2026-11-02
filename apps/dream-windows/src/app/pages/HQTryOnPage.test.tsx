import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HQTryOnPage } from "./HQTryOnPage";
import type { HQJob, HQRole } from "../../domain/hq-tryon";
import { defaultHQParameters, hqExecutionBasis } from "../../domain/hq-tryon";
import { hqApi, hqFingerprint, readHQDraft, readHQOperations, saveHQOperation, writeHQDraft } from "../../providers/hq-tryon-api";
import { identityApi } from "../../providers/identity-api";
import { refinementApi } from "../../providers/refinement-api";
import { identityDefaults } from "../../domain/identity";
import type { IdentityJob, IdentityProfile } from "../../domain/identity";
import { announceImageDeleted } from "../image-deletion";

const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>("node:crypto");
const ids = { person: "a".repeat(64), garment: "SPR-0087", pose: "P001" };
const ready = { configured: true, authorized: true, modelReady: true, pipeline: hqExecutionBasis };
const asset = (role: HQRole) => ({ id: ids[role], label: `${role}-original` });
const personProfile: IdentityProfile = { id: "person-test", name: "测试素颜档案", referenceId: "ref-test", faceIndex: 0, state: "ready", referenceKind: "faceid", defaults: {}, error: null, createdAt: "2026-11-02", updatedAt: "2026-11-02" };
const matureJob = (): IdentityJob => ({ id: "identity-hq-test", state: "complete", progress: 100, message: "底图及可选换脸已完成", request: { ...identityDefaults, referenceId: "ref-test", faceIndex: 0, facePolish: true, faceRestoreStrength: .35 }, error: null,
  result: { imageUrl: "/api/history/identity-hq-test/image", metadata: { facePolish: { enabled: true, status: "completed", originalImageUrl: "/api/identity/jobs/identity-hq-test/original" } } } });
const createJob = (overrides: Partial<HQJob> = {}): HQJob => ({ id: "hq-job-a", state: "queued", phase: "queued", progress: 0,
  inputs: (["person", "garment", "pose"] as const).map(role => ({ ...asset(role), role, sha256: "b".repeat(64), width: 512, height: 768 })),
  parameters: defaultHQParameters, ...overrides });
const deferred = <T,>() => { let resolve!: (value: T) => void, reject!: (reason: unknown) => void; const promise = new Promise<T>((r, e) => { resolve = r; reject = e; }); return { resolve, reject, promise }; };

beforeEach(() => {
  sessionStorage.clear(); localStorage.clear();
  vi.stubGlobal("crypto", webcrypto);
  vi.spyOn(identityApi, "profiles").mockResolvedValue([]);
  vi.spyOn(identityApi, "profile").mockResolvedValue(personProfile);
  vi.spyOn(identityApi, "status").mockResolvedValue({ ready: true, modelName: "Realistic Vision", message: "就绪", loras: [], facePolish: { ready: true, message: "可选修脸可用" } });
  vi.spyOn(identityApi, "job").mockResolvedValue(matureJob());
  vi.spyOn(refinementApi, "list").mockResolvedValue({ sourceJobId: "identity-hq-test", selectedVersionId: "result", modes: ["restore"],
    versions: [{ id: "result", state: "complete", message: "完成", createdAt: "2026-11-02", parentVersionId: null, settings: {}, imageUrl: "/api/history/identity-hq-test/image" }] });
  vi.spyOn(hqApi, "status").mockResolvedValue(ready);
  vi.spyOn(hqApi, "jobs").mockResolvedValue([]);
  vi.spyOn(hqApi, "job").mockImplementation(async id => createJob({ id }));
  vi.spyOn(hqApi, "catalog").mockImplementation(async role => ({ items: [asset(role)], total: 1, hasMore: false, categories: ["春", "派对"] }));
  vi.spyOn(hqApi, "create").mockImplementation(async body => createJob({ idempotencyKey: body.idempotencyKey }));
  vi.spyOn(hqApi, "cancel").mockImplementation(async id => createJob({ id, state: "cancelled" }));
  vi.spyOn(hqApi, "result").mockResolvedValue(new Blob(["verified-pixels"], { type: "image/png" }));
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:hq-verified") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function chooseThree() {
  fireEvent.click(await screen.findByRole("button", { name: "选择人物 person-original" }));
  fireEvent.click(screen.getByRole("tab", { name: "服装" }));
  fireEvent.click(await screen.findByRole("button", { name: "选择服装 garment-original" }));
  fireEvent.click(screen.getByRole("tab", { name: "姿势" }));
  fireEvent.click(await screen.findByRole("button", { name: "选择姿势 pose-original" }));
}
function saveSelection() { writeHQDraft({ selection: { person: asset("person"), garment: asset("garment"), pose: asset("pose") }, parameters: defaultHQParameters }); }

describe("HQ local workflow", () => {
  it.each([true, false])("adopts another browser's successful successor on refresh, following only the superseded selection (viewing B=%s)", async viewingB => {
    const a = createJob({ id: "hq-attempt-a", state: "failed", phase: "failed", pipeline: hqExecutionBasis, identityJobId: "identity-a", idempotencyKey: "hq-key-attempt-a", createdAt: "2026-11-02T01:00:00+00:00" });
    const b = { ...a, id: "hq-attempt-b", identityJobId: "identity-b", idempotencyKey: "hq-key-attempt-b", createdAt: "2026-11-02T02:00:00+00:00" };
    const c = { ...b, id: "hq-attempt-c", state: "succeeded" as const, phase: "complete", identityJobId: "identity-hq-test", idempotencyKey: "hq-key-attempt-c", createdAt: "2026-11-02T03:00:00.123456+00:00", result: { sha256: "c".repeat(64) } };
    const selection = { person: asset("person"), garment: asset("garment"), pose: asset("pose") };
    const fingerprint = hqFingerprint({ personId: ids.person, garmentId: ids.garment, poseId: ids.pose, parameters: defaultHQParameters });
    saveHQOperation({ fingerprint, delivery: "submitted", jobId: b.id, idempotencyKey: b.idempotencyKey, retryOf: a.id });
    writeHQDraft({ selection, parameters: defaultHQParameters, activeJobId: viewingB ? b.id : a.id });
    vi.mocked(hqApi.jobs).mockResolvedValue([a, b]);
    vi.mocked(hqApi.job).mockImplementation(async id => [a, b, c].find(item => item.id === id)!);
    render(<HQTryOnPage />);
    await screen.findByRole("heading", { name: `任务 ${viewingB ? b.id : a.id}` });
    if (viewingB) expect(await screen.findByRole("button", { name: "按相同设置新建重试" })).toBeEnabled();

    // A second browser completed C. The list can put the matching old B before C.
    vi.mocked(hqApi.jobs).mockResolvedValue([b, a, c]);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "刷新任务" })));
    expect(readHQOperations().find(row => row.fingerprint === fingerprint)).toMatchObject({ jobId: c.id, idempotencyKey: c.idempotencyKey, delivery: "submitted" });
    expect(await screen.findByRole("heading", { name: `任务 ${viewingB ? c.id : a.id}` })).toBeVisible();
    expect(screen.queryByRole("button", { name: "按相同设置新建重试" })).not.toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "查看本组已有任务" })));
    expect(await screen.findByRole("heading", { name: `任务 ${c.id}` })).toBeVisible();
    expect(readHQDraft()).toMatchObject({ selection, parameters: defaultHQParameters });
    expect(hqApi.create).not.toHaveBeenCalled(); expect(hqApi.cancel).not.toHaveBeenCalled();
  });

  it.each(["failed", "cancelled"] as const)("creates one new attempt for explicitly retried %s settings while preserving the old job", async state => {
    const parameters = { width: 768, height: 1152, seed: 20261104, steps: 30 };
    const options = { profileId: personProfile.id, facePolish: true, faceRestoreStrength: .4 };
    const old = createJob({ state, phase: state, pipeline: hqExecutionBasis, identityJobId: "identity-old", idempotencyKey: "hq-old-terminal-key", parameters, ...options });
    writeHQDraft({ selection: { person: asset("person"), garment: asset("garment"), pose: asset("pose") }, activeJobId: old.id, parameters, ...options });
    const gate = deferred<HQJob>();
    vi.mocked(hqApi.jobs).mockResolvedValue([old]); vi.mocked(hqApi.job).mockResolvedValue(old); vi.mocked(hqApi.create).mockReturnValue(gate.promise);
    render(<HQTryOnPage />);
    await screen.findByRole("button", { name: "按相同设置新建重试" });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "查看本组已有任务" })));
    expect(hqApi.create).not.toHaveBeenCalled();
    const retry = await screen.findByRole("button", { name: "按相同设置新建重试" });
    fireEvent.click(retry); fireEvent.click(retry);
    await waitFor(() => expect(hqApi.create).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(hqApi.create).mock.calls[0][0];
    expect(sent.idempotencyKey).not.toBe(old.idempotencyKey);
    expect(sent).toMatchObject({ personId: ids.person, garmentId: ids.garment, poseId: ids.pose, parameters, ...options });
    expect(readHQDraft()).toMatchObject({ parameters, ...options });
    const created = { ...old, id: "hq-retry-new", state: "queued" as const, phase: "queued", idempotencyKey: sent.idempotencyKey };
    vi.mocked(hqApi.jobs).mockResolvedValue([old, created]); vi.mocked(hqApi.job).mockImplementation(async id => id === old.id ? old : created);
    await act(async () => gate.resolve(created));
    expect(await screen.findByRole("heading", { name: "任务 hq-retry-new" })).toBeVisible();
    expect(screen.getByRole("button", { name: new RegExp(`${state === "failed" ? "失败" : "已取消"} ${old.id}`) })).toBeVisible();
    expect(readHQOperations()[0]).toMatchObject({ idempotencyKey: sent.idempotencyKey, jobId: created.id });
    expect(hqApi.cancel).not.toHaveBeenCalled();
  });

  it("keeps the explicit retry key after a lost POST, old-job refresh and remount; only resends on a human click", async () => {
    saveSelection();
    const old = createJob({ state: "failed", phase: "failed", pipeline: hqExecutionBasis, identityJobId: "identity-old", idempotencyKey: "hq-old-failed-key" });
    vi.mocked(hqApi.jobs).mockResolvedValue([old]); vi.mocked(hqApi.job).mockResolvedValue(old);
    vi.mocked(hqApi.create).mockRejectedValueOnce(new Error("response lost")).mockImplementationOnce(async body => createJob({ id: "hq-recovered-retry", idempotencyKey: body.idempotencyKey }));
    const view = render(<HQTryOnPage />);
    fireEvent.click(await screen.findByRole("button", { name: "按相同设置新建重试" }));
    await screen.findByText(/提交未确认：response lost/);
    const key = vi.mocked(hqApi.create).mock.calls[0][0].idempotencyKey;
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "刷新任务" })));
    expect(screen.queryByRole("button", { name: "按相同设置新建重试" })).not.toBeInTheDocument();
    view.unmount(); render(<HQTryOnPage />);
    const resend = await screen.findByRole("button", { name: "重发同一请求" });
    await waitFor(() => expect(resend).toBeEnabled());
    expect(hqApi.create).toHaveBeenCalledTimes(1);
    expect(readHQOperations()[0]).toMatchObject({ idempotencyKey: key, delivery: "unknown" });
    await act(async () => { fireEvent.click(resend); fireEvent.click(resend); });
    expect(hqApi.create).toHaveBeenCalledTimes(2);
    expect(vi.mocked(hqApi.create).mock.calls[1][0].idempotencyKey).toBe(key);
  });

  it("waits for authoritative terminal detail and hides explicit retry during refresh or after a settings change", async () => {
    saveSelection();
    const old = createJob({ state: "failed", phase: "failed", pipeline: hqExecutionBasis, identityJobId: "identity-old", idempotencyKey: "hq-old-failed-key" });
    const initial = deferred<HQJob>(), refreshed = deferred<HQJob>();
    vi.mocked(hqApi.jobs).mockResolvedValue([old]); vi.mocked(hqApi.job).mockReturnValueOnce(initial.promise).mockReturnValueOnce(refreshed.promise);
    render(<HQTryOnPage />); await screen.findByRole("button", { name: "查看本组已有任务" });
    expect(screen.queryByRole("button", { name: "按相同设置新建重试" })).not.toBeInTheDocument();
    await act(async () => initial.resolve(old));
    expect(await screen.findByRole("button", { name: "按相同设置新建重试" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    expect(screen.queryByRole("button", { name: "按相同设置新建重试" })).not.toBeInTheDocument();
    await act(async () => refreshed.resolve(old));
    await screen.findByRole("button", { name: "按相同设置新建重试" });
    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "1" } });
    expect(screen.queryByRole("button", { name: "按相同设置新建重试" })).not.toBeInTheDocument();
    expect(hqApi.create).not.toHaveBeenCalled();
  });

  it.each(["queued", "running", "succeeded"] as const)("never offers a new retry for authoritative %s, including unconfirmed cancellation", async state => {
    saveSelection();
    const existing = createJob({ state, phase: state, pipeline: hqExecutionBasis, identityJobId: "identity-hq-test", idempotencyKey: "hq-existing-key", cancellationRequested: state === "running" });
    vi.mocked(hqApi.jobs).mockResolvedValue([existing]); vi.mocked(hqApi.job).mockResolvedValue(existing);
    render(<HQTryOnPage />); await screen.findByRole("heading", { name: `任务 ${existing.id}` });
    expect(screen.queryByRole("button", { name: "按相同设置新建重试" })).not.toBeInTheDocument();
    expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("offers the HQ upscale shortcut only after capability confirmation and opens the same workspace without generating", async () => {
    const completed = createJob({ state: "succeeded", identityJobId: "identity-hq-test", result: { sha256: "c".repeat(64) } });
    vi.mocked(hqApi.jobs).mockResolvedValue([completed]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    const gate = deferred<Awaited<ReturnType<typeof refinementApi.list>>>();
    vi.mocked(refinementApi.list).mockReturnValue(gate.promise);
    const create = vi.spyOn(refinementApi, "create");
    render(<HQTryOnPage />); await screen.findByRole("button", { name: "独立精修与版本对比" });
    expect(screen.queryByRole("button", { name: "2倍清晰增强" })).not.toBeInTheDocument();
    await act(async () => gate.resolve({ sourceJobId: "identity-hq-test", selectedVersionId: "result", modes: ["restore", "upscale"], defaultMode: "restore",
      versions: [{ id: "result", state: "complete", message: "完成", createdAt: "2026-11-02", parentVersionId: null, settings: {}, imageUrl: "/api/history/identity-hq-test/image", width: 512, height: 768 }] }));
    fireEvent.click(await screen.findByRole("button", { name: "2倍清晰增强" }));
    expect(await screen.findByRole("button", { name: "开始2倍清晰增强" })).toBeEnabled();
    expect(screen.getByLabelText("精修模式")).toHaveValue("upscale");
    expect(screen.getAllByRole("region", { name: "独立精修工作区" })).toHaveLength(1);
    expect(create).not.toHaveBeenCalled(); expect(hqApi.create).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "下载成片原图" })).toHaveAttribute("href", "blob:hq-verified");
    expect(screen.getByRole("link", { name: "修脸结果：打开原图 / 放大查看" })).toHaveAttribute("href", expect.stringMatching(/^\/api\/history\/identity-hq-test\/image/));
  });

  it.each([[], ["restore"], undefined])("keeps HQ upscale hidden when the service does not advertise it: %s", async modes => {
    const completed = createJob({ state: "succeeded", identityJobId: "identity-hq-test", result: { sha256: "c".repeat(64) } });
    vi.mocked(hqApi.jobs).mockResolvedValue([completed]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    vi.mocked(refinementApi.list).mockResolvedValue({ sourceJobId: "identity-hq-test", selectedVersionId: "result", modes, versions: [] });
    render(<HQTryOnPage />); await screen.findByRole("button", { name: "独立精修与版本对比" });
    await waitFor(() => expect(refinementApi.list).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "2倍清晰增强" })).not.toBeInTheDocument();
  });

  it("starts with the approved HD preset and preserves seed and steps across resolution changes", async () => {
    saveSelection(); render(<HQTryOnPage />);
    const preset = await screen.findByRole("combobox", { name: "尺寸预设" });
    expect(preset).toHaveValue("768x1152");
    fireEvent.change(preset, { target: { value: "512x768" } });
    expect(screen.getByLabelText("宽度")).toHaveValue(512);
    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "20261102" } });
    fireEvent.change(screen.getByLabelText("步数"), { target: { value: "30" } });
    fireEvent.change(preset, { target: { value: "768x1152" } });
    expect(screen.getByLabelText("宽度")).toHaveValue(768);
    expect(screen.getByLabelText("高度")).toHaveValue(1152);
    expect(screen.getByText(/高清生成更慢，显存占用更高/)).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "本机生成" })));
    expect(vi.mocked(hqApi.create).mock.calls[0][0].parameters).toEqual({ seed: 20261102, steps: 30, width: 768, height: 1152 });
  });

  it("retains a custom draft across role switches and remounts, including the new landscape presets", async () => {
    writeHQDraft({ selection: { person: asset("person") }, parameters: { seed: 42, steps: 30, width: 704, height: 896 } });
    const view = render(<HQTryOnPage />);
    expect(await screen.findByLabelText("尺寸预设")).toHaveValue("custom");
    expect(screen.getByLabelText("宽度")).toHaveValue(704);
    fireEvent.click(screen.getByRole("tab", { name: "服装" }));
    await screen.findByRole("button", { name: "选择服装 garment-original" });
    expect(screen.getByLabelText("高度")).toHaveValue(896);
    fireEvent.change(screen.getByLabelText("尺寸预设"), { target: { value: "960x640" } });
    view.unmount(); render(<HQTryOnPage />);
    expect(await screen.findByLabelText("尺寸预设")).toHaveValue("960x640");
    expect(screen.getByLabelText("宽度")).toHaveValue(960);
    expect(screen.getByLabelText("高度")).toHaveValue(640);
    expect(screen.getByLabelText("种子")).toHaveValue(42);
    expect(screen.getByLabelText("步数")).toHaveValue(30);
    expect(screen.getByRole("img", { name: "已选人物原图" })).toHaveAttribute("src", hqApi.assetUrl("person", ids.person));
    expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("keeps profile optional and face polish off, then sends explicit profile/face choices without replacing the R2 person", async () => {
    saveSelection(); vi.mocked(identityApi.profiles).mockResolvedValue([personProfile, { ...personProfile, id: "visual-profile", name: "视觉档案", referenceKind: "visual" }]);
    render(<HQTryOnPage />);
    const select = await screen.findByRole("combobox", { name: "固定人物档案（可选）" });
    await screen.findByRole("option", { name: /测试素颜档案/ });
    expect(select).toHaveValue(""); expect(screen.queryByRole("option", { name: /视觉档案/ })).not.toBeInTheDocument();
    const polish = screen.getByRole("checkbox", { name: "生成后修脸（可选）" }); expect(polish).not.toBeChecked();
    fireEvent.change(select, { target: { value: personProfile.id } });
    await waitFor(() => expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled());
    expect(screen.getByRole("img", { name: "已选人物原图" })).toHaveAttribute("src", hqApi.assetUrl("person", ids.person));
    fireEvent.click(polish); expect(screen.getByRole("spinbutton", { name: "面部细节修复强度" })).toHaveValue(.35);
    expect(screen.getByText(/0–1，默认 0.35/)).toBeVisible();
    fireEvent.change(screen.getByRole("spinbutton", { name: "面部细节修复强度" }), { target: { value: "1.1" } });
    expect(screen.getByRole("button", { name: "本机生成" })).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton", { name: "面部细节修复强度" }), { target: { value: ".35" } });
    vi.mocked(hqApi.create).mockRejectedValueOnce(new Error("PROFILE_PERSON_MISMATCH：人物不匹配"));
    fireEvent.click(screen.getByRole("button", { name: "本机生成" }));
    await screen.findByText(/PROFILE_PERSON_MISMATCH/);
    expect(vi.mocked(hqApi.create).mock.calls[0][0]).toMatchObject({ personId: ids.person, profileId: personProfile.id, facePolish: true, faceRestoreStrength: .35, parameters: defaultHQParameters });
    expect(screen.getByRole("img", { name: "已选人物原图" })).toHaveAttribute("src", hqApi.assetUrl("person", ids.person));
    expect(screen.queryByRole("combobox", { name: /模型/ })).not.toBeInTheDocument();
  });

  it("reuses original/result switching and the existing refinement workspace for the linked identity job", async () => {
    const completed = createJob({ state: "succeeded", phase: "complete", identityJobId: "identity-hq-test", result: { sha256: "c".repeat(64) } });
    vi.mocked(hqApi.jobs).mockResolvedValue([completed]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    const list = vi.spyOn(refinementApi, "list").mockResolvedValue({ sourceJobId: "identity-hq-test", selectedVersionId: "result", modes: ["restore", "edge-lighting"], usesDiffusion: false,
      versions: ["result", "original"].map(id => ({ id, state: "complete", message: "完成", createdAt: "2026-11-02", parentVersionId: null, settings: {}, imageUrl: `/api/identity/jobs/identity-hq-test/${id}` })) });
    render(<HQTryOnPage />);
    fireEvent.click(await screen.findByRole("button", { name: "查看生成原图" }));
    expect(screen.getByRole("img", { name: "生成原图" })).toHaveAttribute("src", "/api/identity/jobs/identity-hq-test/original");
    fireEvent.click(screen.getByRole("button", { name: "查看修脸结果" }));
    expect(screen.getByRole("img", { name: "修脸结果" }).getAttribute("src")).toMatch(/^\/api\/history\/identity-hq-test\/image\?/);
    fireEvent.click(screen.getByRole("button", { name: "独立精修与版本对比" }));
    expect(await screen.findByRole("group", { name: "精修版本与父图选择" })).toBeVisible();
    expect(list).toHaveBeenCalledWith("identity-hq-test", expect.any(AbortSignal));
    expect(screen.getByRole("link", { name: "下载当前版本" })).toHaveAttribute("download", "identity-hq-test-result.png");
    expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("does not query an identity child before preparation finishes and renders real Chinese event stages", async () => {
    const queued = createJob({ identityJobId: "identity-hq-test", phase: "downloading", inputs: [], requestedInputIds: ids });
    vi.mocked(hqApi.jobs).mockResolvedValue([queued]); vi.mocked(hqApi.job).mockResolvedValue(queued);
    render(<HQTryOnPage />); await screen.findByText(/排队中 · 读取三图原图/); expect(identityApi.job).not.toHaveBeenCalled();
    vi.mocked(hqApi.job).mockResolvedValue({ ...queued, state: "running", phase: "sampling", progress: 37 });
    vi.mocked(identityApi.job).mockResolvedValue({ ...matureJob(), state: "sampling", message: "正在采样第 11 步", result: null });
    fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    expect(await screen.findByText("人物处理：正在采样第 11 步")).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "本机任务进度" })).toHaveAttribute("value", "37");
    expect(screen.queryByText(/sampling/)).not.toBeInTheDocument();
  });

  it("shows normal preparation for the current pipeline before an identity child exists", async () => {
    const pending = createJob({ pipeline: hqExecutionBasis, identityJobId: null, state: "queued", phase: "downloading", inputs: [], requestedInputIds: ids });
    vi.mocked(hqApi.jobs).mockResolvedValue([pending]); vi.mocked(hqApi.job).mockResolvedValue(pending);
    render(<HQTryOnPage />);
    expect(await screen.findByText("排队中 · 读取三图原图")).toBeVisible();
    expect(screen.queryByText("旧独立管线试验 · 尚未验证成熟人物流程")).not.toBeInTheDocument();
    expect(screen.getAllByText("原图尚未准备完成")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "独立精修与版本对比" })).not.toBeInTheDocument();
    expect(identityApi.job).not.toHaveBeenCalled(); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it.each(["historyDeleted", "resultDeleted"] as const)("respects the server %s tombstone before reading either output endpoint", async deletedFlag => {
    const deleted = createJob({ state: "succeeded", phase: "complete", identityJobId: "identity-hq-test", [deletedFlag]: true, refinementsAvailable: false, result: null });
    vi.mocked(hqApi.jobs).mockResolvedValue([deleted]); vi.mocked(hqApi.job).mockResolvedValue(deleted);
    render(<HQTryOnPage />); await screen.findByText("人物结果已从历史删除，任务参数与输入记录保留。");
    expect(identityApi.job).not.toHaveBeenCalled(); expect(hqApi.result).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "独立精修与版本对比" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载成片原图" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开人物输入原图" })).toBeVisible();
  });

  it("removes linked previews and ignores an in-flight blob after a confirmed history deletion", async () => {
    const completed = createJob({ state: "succeeded", phase: "complete", identityJobId: "identity-hq-test", result: { sha256: "c".repeat(64) } });
    const result = deferred<Blob>(); vi.mocked(hqApi.result).mockReturnValue(result.promise);
    vi.mocked(hqApi.jobs).mockResolvedValue([completed]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    render(<HQTryOnPage />); await screen.findByRole("button", { name: "独立精修与版本对比" });
    await act(async () => announceImageDeleted("identity-hq-test"));
    expect(screen.getByText("人物结果已从历史删除，任务参数与输入记录保留。")).toBeVisible();
    await act(async () => result.resolve(new Blob(["late-result"], { type: "image/png" })));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "独立精修与版本对比" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "修脸结果" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "下载成片原图" })).not.toBeInTheDocument();
  });

  it("labels old pipeline records, shortens long IDs and copies the full ID", async () => {
    const id = "hq-" + "a".repeat(64), old = createJob({ id, state: "succeeded", phase: "complete", result: { sha256: "c".repeat(64) } });
    vi.mocked(hqApi.jobs).mockResolvedValue([old]); vi.mocked(hqApi.job).mockResolvedValue(old);
    const writeText = vi.fn().mockResolvedValue(undefined); Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<HQTryOnPage />); await screen.findByText("旧独立管线试验 · 尚未验证成熟人物流程");
    const heading = screen.getByRole("heading", { name: /^任务 hq-/ }); expect(heading).toHaveAttribute("title", id); expect(heading.textContent?.length).toBeLessThan(35);
    fireEvent.click(screen.getByRole("button", { name: "复制完整任务编号" })); await waitFor(() => expect(writeText).toHaveBeenCalledWith(id));
    expect(screen.queryByRole("button", { name: "独立精修与版本对比" })).not.toBeInTheDocument();
  });

  it("selects three correctly assigned originals, creates once, and exposes local input links", async () => {
    const pending = deferred<HQJob>(); vi.mocked(hqApi.create).mockReturnValue(pending.promise);
    render(<HQTryOnPage />); await chooseThree();
    for (const role of ["person", "garment", "pose"] as const) {
      const label = { person: "人物", garment: "服装", pose: "姿势" }[role];
      expect(screen.getByRole("img", { name: `已选${label}原图` })).toHaveAttribute("src", hqApi.assetUrl(role, ids[role]));
    }
    const button = screen.getByRole("button", { name: "本机生成" }); fireEvent.click(button); fireEvent.click(button);
    expect(hqApi.create).toHaveBeenCalledTimes(1);
    const sent = vi.mocked(hqApi.create).mock.calls[0][0];
    expect(sent).toEqual({ personId: ids.person, garmentId: ids.garment, poseId: ids.pose, parameters: defaultHQParameters, facePolish: true, faceRestoreStrength: .35, idempotencyKey: expect.stringMatching(/^hq-local-/) });
    await act(async () => pending.resolve(createJob({ idempotencyKey: sent.idempotencyKey })));
    expect(await screen.findByRole("button", { name: "查看本组已有任务" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "查看本组已有任务" }));
    expect(hqApi.create).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("link", { name: "打开人物输入原图" })).toHaveAttribute("href", "/api/hq/jobs/hq-job-a/inputs/person");
    expect(screen.queryByRole("link", { name: "下载成片原图" })).not.toBeInTheDocument();
  });

  it("keeps an uncertain POST recoverable across remount and reuses its key only on explicit retry", async () => {
    saveSelection(); vi.mocked(hqApi.create).mockRejectedValueOnce(new Error("connection lost"));
    const view = render(<HQTryOnPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "本机生成" }));
    await screen.findByText(/提交未确认：connection lost/);
    const key = vi.mocked(hqApi.create).mock.calls[0][0].idempotencyKey;
    view.unmount(); render(<HQTryOnPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新任务" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    await waitFor(() => expect(hqApi.jobs).toHaveBeenCalledTimes(3));
    expect(hqApi.create).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "重发同一请求" }));
    await waitFor(() => expect(hqApi.create).toHaveBeenCalledTimes(2));
    expect(vi.mocked(hqApi.create).mock.calls[1][0].idempotencyKey).toBe(key);
  });

  it("reconciles a lost receipt from the local job list without another create", async () => {
    saveSelection(); vi.mocked(hqApi.create).mockRejectedValueOnce(new Error("timeout"));
    render(<HQTryOnPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "本机生成" })); await screen.findByText(/提交未确认：timeout/);
    const request = readHQOperations()[0];
    vi.mocked(hqApi.jobs).mockResolvedValue([createJob({ pipeline: hqExecutionBasis, identityJobId: "identity-hq-test", idempotencyKey: request.idempotencyKey })]);
    fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    expect(await screen.findByRole("button", { name: "查看本组已有任务" })).toBeEnabled();
    expect(readHQOperations()[0].jobId).toBe("hq-job-a"); expect(hqApi.create).toHaveBeenCalledTimes(1);
  });

  it("restores a server job by all three roles and parameters before creating any key in a new session", async () => {
    saveSelection();
    const startup = deferred<HQJob[]>(), existing = createJob({ state: "succeeded", pipeline: hqExecutionBasis, identityJobId: "identity-hq-test", idempotencyKey: "hq-local-old-browser-key" });
    vi.mocked(hqApi.jobs).mockReturnValue(startup.promise); vi.mocked(hqApi.job).mockResolvedValue(existing);
    render(<HQTryOnPage />);
    expect(screen.getByRole("button", { name: "本机生成" })).toBeDisabled();
    await act(async () => startup.resolve([existing]));
    const view = await screen.findByRole("button", { name: "查看本组已有任务" });
    await act(async () => fireEvent.click(view));
    expect(hqApi.create).not.toHaveBeenCalled(); expect(readHQOperations()[0].idempotencyKey).toBe(existing.idempotencyKey);
  });

  it("keeps prototype history visible but creates a new-basis request despite a matching legacy receipt and server record", async () => {
    saveSelection();
    const legacy = createJob({ id: "hq-prototype", state: "succeeded", phase: "complete", pipeline: "hq-three-image-sd15-v1", idempotencyKey: "hq-local-prototype-request", result: { sha256: "c".repeat(64) } });
    const fingerprint = JSON.stringify([ids.person, ids.garment, ids.pose, 0, 512, 768, 24]);
    localStorage.setItem("dream.hq.operations.v1", JSON.stringify([{ fingerprint, idempotencyKey: legacy.idempotencyKey, jobId: legacy.id, delivery: "submitted" }]));
    vi.mocked(hqApi.jobs).mockResolvedValue([legacy]); vi.mocked(hqApi.job).mockResolvedValue(legacy);
    vi.mocked(hqApi.create).mockImplementation(async body => {
      const created = createJob({ id: "hq-current", pipeline: hqExecutionBasis, identityJobId: "identity-hq-current", phase: "downloading", inputs: [], requestedInputIds: ids, idempotencyKey: body.idempotencyKey });
      vi.mocked(hqApi.jobs).mockResolvedValue([created, legacy]);
      vi.mocked(hqApi.job).mockImplementation(async id => id === legacy.id ? legacy : created);
      return created;
    });
    render(<HQTryOnPage />);
    await screen.findByText("旧独立管线试验 · 尚未验证成熟人物流程");
    expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled(); expect(hqApi.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "本机生成" }));
    const existing = await screen.findByRole("button", { name: "查看本组已有任务" });
    expect(hqApi.create).toHaveBeenCalledTimes(1);
    expect(vi.mocked(hqApi.create).mock.calls[0][0].idempotencyKey).toContain(hqExecutionBasis);
    expect(vi.mocked(hqApi.create).mock.calls[0][0].idempotencyKey).not.toBe(legacy.idempotencyKey);
    expect(screen.getByRole("button", { name: /已完成 hq-prototype/ })).toBeVisible();
    await act(async () => fireEvent.click(existing)); expect(hqApi.create).toHaveBeenCalledTimes(1);
    expect(readHQOperations()).toHaveLength(1); expect(readHQOperations()[0].jobId).toBe("hq-current");
  });

  it("keeps a queued download cancellable while its POST is pending and ignores its later stale queued receipt", async () => {
    vi.useFakeTimers();
    saveSelection(); const pending = deferred<HQJob>(); vi.mocked(hqApi.create).mockReturnValue(pending.promise);
    await act(async () => { render(<HQTryOnPage />); });
    expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "本机生成" })));
    const queued = createJob({ phase: "downloading", inputs: [], requestedInputIds: ids, idempotencyKey: vi.mocked(hqApi.create).mock.calls[0][0].idempotencyKey });
    vi.mocked(hqApi.jobs).mockResolvedValue([queued]); vi.mocked(hqApi.job).mockResolvedValue(queued);
    expect(screen.getByRole("button", { name: "刷新任务" })).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(hqApi.jobs).toHaveBeenCalledTimes(2);
    const cancel = screen.getByRole("button", { name: "取消任务" }); expect(cancel).toBeEnabled();
    const cancelled = { ...queued, state: "cancelled" as const, phase: "cancelled", cancellationRequested: true };
    vi.mocked(hqApi.cancel).mockImplementation(async () => { vi.mocked(hqApi.jobs).mockResolvedValue([cancelled]); vi.mocked(hqApi.job).mockResolvedValue(cancelled); return cancelled; });
    await act(async () => fireEvent.click(cancel)); expect(hqApi.cancel).toHaveBeenCalledWith(queued.id);
    expect(screen.getByText("任务已取消。")).toBeVisible();
    await act(async () => pending.resolve(queued));
    expect(within(screen.getByRole("region", { name: "本机试衣任务" })).getByRole("status")).toHaveTextContent("已取消");
    expect(hqApi.create).toHaveBeenCalledTimes(1);
  });

  it("keeps polling a nonterminal cancellation request until the backend confirms cancellation", async () => {
    vi.useFakeTimers();
    const running = createJob({ state: "running", phase: "downloading", pipeline: hqExecutionBasis, identityJobId: "identity-hq-test" });
    const earlier = createJob({ id: "hq-earlier", state: "succeeded", phase: "complete", result: { sha256: "c".repeat(64) } });
    const requested = { ...running, phase: "cancelling", cancellationRequested: true };
    vi.mocked(hqApi.jobs).mockResolvedValue([running, earlier]); vi.mocked(hqApi.job).mockImplementation(async id => id === earlier.id ? earlier : running);
    vi.mocked(hqApi.cancel).mockImplementation(async () => {
      vi.mocked(hqApi.jobs).mockResolvedValue([requested, earlier]); vi.mocked(hqApi.job).mockImplementation(async id => id === earlier.id ? earlier : requested); return requested;
    });
    await act(async () => { render(<HQTryOnPage />); });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "取消任务" })));
    const detail = within(screen.getByRole("region", { name: "本机试衣任务" }));
    expect(detail.getByRole("status")).toHaveTextContent("运行中 · 已请求取消，等待确认");
    expect(screen.getByText("已请求取消，等待本机任务确认。")).toBeVisible();
    expect(screen.getByRole("button", { name: "取消任务" })).toBeDisabled();
    expect(screen.queryByText("任务已取消。")).not.toBeInTheDocument();
    const beforePoll = vi.mocked(hqApi.job).mock.calls.length;
    const cancelled = { ...requested, state: "cancelled" as const, phase: "cancelled" };
    vi.mocked(hqApi.jobs).mockResolvedValue([cancelled, earlier]); vi.mocked(hqApi.job).mockImplementation(async id => id === earlier.id ? earlier : cancelled);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(hqApi.job).toHaveBeenCalledTimes(beforePoll + 1); expect(detail.getByRole("status")).toHaveTextContent("已取消");
    expect(screen.getByText("任务已取消。")).toBeVisible();
    expect(screen.queryByText("已请求取消，等待本机任务确认。")).not.toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /已完成 hq-earlier/ })));
    expect(screen.getByRole("heading", { name: "任务 hq-earlier" })).toBeVisible();
    expect(screen.queryByText("任务已取消。")).not.toBeInTheDocument();
    expect(hqApi.cancel).toHaveBeenCalledTimes(1); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("clears notices on task selection and ignores cancellation feedback that arrives for a previous selection", async () => {
    const running = createJob({ state: "running" }), earlier = createJob({ id: "hq-earlier", state: "failed", phase: "failed" });
    const pending = deferred<HQJob>(); vi.mocked(hqApi.cancel).mockReturnValue(pending.promise);
    vi.mocked(hqApi.jobs).mockResolvedValue([running, earlier]); vi.mocked(hqApi.job).mockImplementation(async id => id === earlier.id ? earlier : running);
    const writeText = vi.fn().mockResolvedValue(undefined); Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<HQTryOnPage />);
    fireEvent.click(await screen.findByRole("button", { name: "复制完整任务编号" }));
    await screen.findByText("完整任务编号已复制。");
    fireEvent.click(screen.getByRole("button", { name: "取消任务" }));
    fireEvent.click(screen.getByRole("button", { name: /失败 hq-earlier/ }));
    await screen.findByRole("heading", { name: "任务 hq-earlier" });
    expect(screen.queryByText("完整任务编号已复制。")).not.toBeInTheDocument();
    await act(async () => pending.resolve({ ...running, phase: "cancelling", cancellationRequested: true }));
    expect(screen.queryByText("已请求取消，等待本机任务确认。")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "任务 hq-earlier" })).toBeVisible();
    expect(hqApi.cancel).toHaveBeenCalledTimes(1); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("uses a new key for changed seed and recovers the earlier receipt after switching back", async () => {
    saveSelection(); render(<HQTryOnPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "本机生成" })); await screen.findByRole("button", { name: "查看本组已有任务" });
    fireEvent.change(screen.getByRole("spinbutton", { name: "种子" }), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "本机生成" })); await screen.findByRole("button", { name: "查看本组已有任务" });
    expect(vi.mocked(hqApi.create).mock.calls[0][0].idempotencyKey).not.toBe(vi.mocked(hqApi.create).mock.calls[1][0].idempotencyKey);
    fireEvent.change(screen.getByRole("spinbutton", { name: "种子" }), { target: { value: String(defaultHQParameters.seed) } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "查看本组已有任务" }))); expect(hqApi.create).toHaveBeenCalledTimes(2);
  });

  it("discards stale catalog responses and keeps selected IDs through search/category/page changes", async () => {
    const slow = deferred<Awaited<ReturnType<typeof hqApi.catalog>>>();
    vi.mocked(hqApi.catalog).mockImplementation(async (role, q, category, page) => {
      if (role === "person") return slow.promise;
      return { items: [asset(role)], total: 25, categories: ["春"], hasMore: page === 0 };
    });
    render(<HQTryOnPage />); await waitFor(() => expect(hqApi.catalog).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("tab", { name: "服装" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择服装 garment-original" }));
    await act(async () => slow.resolve({ items: [asset("person")], total: 1, categories: [], hasMore: false }));
    expect(screen.queryByRole("button", { name: "选择服装 person-original" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "下一页" })); await waitFor(() => expect(hqApi.catalog).toHaveBeenLastCalledWith("garment", "", "", 1, expect.any(AbortSignal)));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "SPR" } });
    fireEvent.change(screen.getByRole("combobox", { name: "HQ 素材分类" }), { target: { value: "春" } });
    await waitFor(() => expect(hqApi.catalog).toHaveBeenLastCalledWith("garment", "SPR", "春", 0, expect.any(AbortSignal)));
    expect(screen.getByRole("img", { name: "已选服装原图" })).toHaveAttribute("src", hqApi.assetUrl("garment", ids.garment));
  });

  it("never assigns an old catalog ID to a new role image URL, including the commit before effects clear it", async () => {
    const assigned: string[] = [], setAttribute = Element.prototype.setAttribute;
    vi.spyOn(Element.prototype, "setAttribute").mockImplementation(function (this: Element, name, value) {
      if (this.tagName === "IMG" && name === "src") assigned.push(value);
      return setAttribute.call(this, name, value);
    });
    const srcSetter = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src")!.set!;
    vi.spyOn(HTMLImageElement.prototype, "src", "set").mockImplementation(function (this: HTMLImageElement, value) {
      assigned.push(value); srcSetter.call(this, value);
    });
    const garment = deferred<Awaited<ReturnType<typeof hqApi.catalog>>>(), pose = deferred<Awaited<ReturnType<typeof hqApi.catalog>>>();
    const people = Array.from({ length: 7 }, (_, index) => ({ id: String(index + 1).repeat(64), label: `人物 ${index + 1}` }));
    vi.mocked(hqApi.catalog).mockImplementation(async role => role === "person"
      ? { items: people, total: people.length, hasMore: false, categories: ["人物分类"] }
      : role === "garment" ? garment.promise : pose.promise);
    render(<HQTryOnPage />);
    fireEvent.click(await screen.findByRole("button", { name: "选择人物 人物 1" }));
    fireEvent.click(screen.getByRole("tab", { name: "服装" }));
    const gallery = within(screen.getByRole("region", { name: "HQ 原图图库" }));
    expect(gallery.queryAllByRole("button", { name: /^选择/ })).toHaveLength(0);
    expect(gallery.queryByRole("option", { name: "人物分类" })).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "已选人物原图" })).toHaveAttribute("src", hqApi.assetUrl("person", people[0].id));
    const thumbnailURLs = () => assigned.filter(src => src.startsWith("/api/hq/asset?") && src.includes("thumbnail=1")).map(src => new URL(src, "http://localhost"));
    expect(thumbnailURLs().filter(url => url.searchParams.get("kind") === "garment")).toHaveLength(0);
    await act(async () => garment.resolve({ items: [asset("garment")], total: 1, hasMore: false, categories: ["春"] }));
    fireEvent.click(screen.getByRole("button", { name: "选择服装 garment-original" }));
    fireEvent.click(screen.getByRole("tab", { name: "姿势" }));
    expect(gallery.queryAllByRole("button", { name: /^选择/ })).toHaveLength(0);
    expect(thumbnailURLs().filter(url => url.searchParams.get("kind") === "pose")).toHaveLength(0);
    await act(async () => pose.resolve({ items: [asset("pose")], total: 1, hasMore: false, categories: [] }));
    expect(screen.getByRole("button", { name: "选择姿势 pose-original" })).toBeVisible();
    const expectedIds = { person: people.map(item => item.id), garment: [ids.garment], pose: [ids.pose] };
    expect(thumbnailURLs().length).toBeGreaterThanOrEqual(9);
    for (const url of thumbnailURLs()) expect(expectedIds[url.searchParams.get("kind") as HQRole]).toContain(url.searchParams.get("id"));
    expect(screen.getByRole("img", { name: "已选服装原图" })).toHaveAttribute("src", hqApi.assetUrl("garment", ids.garment));
    expect(hqApi.create).not.toHaveBeenCalled();
  });

  it.each([
    { configured: false, authorized: false, modelReady: false },
    { configured: true, authorized: false, modelReady: true },
    { configured: true, authorized: true, modelReady: false },
  ])("blocks create when local readiness is incomplete: %j", async status => {
    saveSelection(); vi.mocked(hqApi.status).mockResolvedValue(status); render(<HQTryOnPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新任务" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "本机生成" })).toBeDisabled(); expect(hqApi.create).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /连接执行器|停止领取/ })).not.toBeInTheDocument();
  });

  it("keeps missing authorization and model status unknown and reports a failed first connection as offline", async () => {
    saveSelection(); const pending = deferred<Awaited<ReturnType<typeof hqApi.status>>>(); vi.mocked(hqApi.status).mockReturnValue(pending.promise);
    render(<HQTryOnPage />);
    const status = within(screen.getByRole("region", { name: "本地 HQ 状态" }));
    expect(status.getByText("正在连接本地服务…")).toBeVisible();
    expect(status.getByText("授权状态未知")).toBeVisible(); expect(status.getByText("模型状态未知")).toBeVisible();
    expect(status.queryByText("图库未授权")).not.toBeInTheDocument(); expect(status.queryByText("模型未就绪")).not.toBeInTheDocument();
    await act(async () => pending.reject(new TypeError("Failed to fetch")));
    expect(status.getByText("本机服务离线")).toBeVisible(); expect(status.getByRole("alert")).toHaveTextContent("Failed to fetch");
    expect(status.queryByText("正在连接本地服务…")).not.toBeInTheDocument();
    expect(status.getByText("授权状态未知")).toBeVisible(); expect(status.getByText("模型状态未知")).toBeVisible();
    expect(screen.getByRole("button", { name: "本机生成" })).toBeDisabled(); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it.each([ready, { configured: false, authorized: false, modelReady: false, error: "旧的配置错误" }])("invalidates cached readiness after a failed refresh and recovers on a new response: %j", async cached => {
    saveSelection(); vi.mocked(hqApi.status).mockResolvedValue(cached);
    render(<HQTryOnPage />); await waitFor(() => expect(screen.getByRole("button", { name: "刷新任务" })).toBeEnabled());
    const status = within(screen.getByRole("region", { name: "本地 HQ 状态" }));
    expect(status.getByText(cached.authorized ? "图库已授权" : "图库未授权")).toBeVisible();
    vi.mocked(hqApi.status).mockRejectedValue(new TypeError("connection closed"));
    fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    expect(await status.findByText("本机服务离线")).toBeVisible();
    expect(status.getByText("授权状态未知")).toBeVisible(); expect(status.getByText("模型状态未知")).toBeVisible();
    expect(status.getByText(/上次状态已过期/)).toBeVisible();
    expect(status.queryByText(/^(已配置|尚未配置|图库已授权|图库未授权|模型文件齐备|模型未就绪|管线：|旧的配置错误)/)).not.toBeInTheDocument();
    expect(status.queryByText(/请在本机完成 HQ 图库授权配置/)).not.toBeInTheDocument();
    expect(status.queryByText(/本地三图管线尚未就绪/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本机生成" })).toBeDisabled();
    vi.mocked(hqApi.status).mockResolvedValue(ready);
    fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    expect(await status.findByText("图库已授权")).toBeVisible();
    expect(status.getByText("模型文件齐备")).toBeVisible(); expect(status.queryByText("本机服务离线")).not.toBeInTheDocument();
    expect(status.queryByText(/上次状态已过期/)).not.toBeInTheDocument(); expect(status.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled(); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("rejects oversized local parameters before POST and reports local service failures", async () => {
    saveSelection(); render(<HQTryOnPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: "本机生成" })).toBeEnabled());
    fireEvent.change(screen.getByRole("spinbutton", { name: "宽度" }), { target: { value: "1152" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "高度" }), { target: { value: "832" } });
    expect(screen.getByRole("button", { name: "本机生成" })).toBeDisabled(); expect(screen.getByText(/总像素不超过 884736/)).toBeVisible();
    vi.mocked(hqApi.status).mockRejectedValue(new Error("offline")); fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    expect(await screen.findByText("本地服务不可用：offline")).toBeVisible(); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("requests cancellation once and displays requested vs confirmed cancellation", async () => {
    const current = createJob({ state: "running", progress: 35 });
    vi.mocked(hqApi.jobs).mockResolvedValue([current]); vi.mocked(hqApi.job).mockResolvedValue(current);
    vi.mocked(hqApi.cancel).mockImplementation(async () => { const value = { ...current, cancellationRequested: true }; vi.mocked(hqApi.job).mockResolvedValue(value); return value; });
    render(<HQTryOnPage />);
    const button = await screen.findByRole("button", { name: "取消任务" }); await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button); fireEvent.click(button);
    expect(await screen.findByText(/运行中.*已请求取消，等待确认/)).toBeVisible(); expect(hqApi.cancel).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "取消任务" })).toBeDisabled();
    vi.mocked(hqApi.job).mockResolvedValue({ ...current, state: "cancelled" });
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新任务" })).toBeEnabled()); fireEvent.click(screen.getByRole("button", { name: "刷新任务" }));
    await waitFor(() => expect(within(screen.getByLabelText("本机试衣任务")).getByText(/^已取消/)).toBeVisible());
    expect(hqApi.result).not.toHaveBeenCalled();
  });

  it("shows real role evidence and audit, waits for checked pixels, then revokes the result URL", async () => {
    const completed = createJob({ state: "succeeded", result: { sha256: "c".repeat(64) }, audit: { bindings: { person: "faceid", garment: "adapter", pose: "controlnet" } } });
    const pixels = deferred<Blob>(); vi.mocked(hqApi.result).mockReturnValue(pixels.promise);
    vi.mocked(hqApi.jobs).mockResolvedValue([completed]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    const view = render(<HQTryOnPage />); await screen.findByText("正在读取并校验成片…");
    expect(screen.queryByRole("link", { name: "下载成片原图" })).not.toBeInTheDocument();
    expect(screen.getByText(/"person": "faceid"/)).toBeInTheDocument();
    await act(async () => pixels.resolve(new Blob(["verified"], { type: "image/png" })));
    expect(await screen.findByRole("link", { name: "下载成片原图" })).toHaveAttribute("href", "blob:hq-verified");
    expect(screen.getByRole("img", { name: "HQ 本机试衣成片" })).toHaveAttribute("src", "blob:hq-verified");
    view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:hq-verified");
  });

  it("blocks a corrupted result and leaves refresh available without recreating the job", async () => {
    const completed = createJob({ state: "succeeded", result: { sha256: "c".repeat(64) } });
    vi.mocked(hqApi.jobs).mockResolvedValue([completed]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    vi.mocked(hqApi.result).mockRejectedValue(new Error("成片 SHA-256 校验失败")); render(<HQTryOnPage />);
    expect(await screen.findByText("成片 SHA-256 校验失败")).toBeVisible();
    expect(screen.queryByRole("link", { name: "下载成片原图" })).not.toBeInTheDocument(); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("polls active jobs without recreating requests, reloading the gallery, or fetching checked pixels again", async () => {
    vi.useFakeTimers();
    const completed = createJob({ state: "succeeded", result: { sha256: "c".repeat(64) } });
    vi.mocked(hqApi.jobs).mockResolvedValue([completed, createJob({ id: "hq-waiting" })]); vi.mocked(hqApi.job).mockResolvedValue(completed);
    await act(async () => { render(<HQTryOnPage />); });
    expect(screen.getByRole("img", { name: "HQ 本机试衣成片" })).toBeVisible();
    expect(hqApi.result).toHaveBeenCalledTimes(1); expect(hqApi.catalog).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(hqApi.jobs).toHaveBeenCalledTimes(2); expect(hqApi.result).toHaveBeenCalledTimes(1); expect(hqApi.catalog).toHaveBeenCalledTimes(1); expect(hqApi.create).not.toHaveBeenCalled();
  });

  it("discards a late detail response after selecting another job", async () => {
    const delayed = deferred<HQJob>(), a = createJob({ id: "hq-a" }), b = createJob({ id: "hq-b", state: "failed", error: { code: "VRAM_OOM", message: "显存不足" } });
    vi.mocked(hqApi.jobs).mockResolvedValue([a, b]); vi.mocked(hqApi.job).mockImplementation(id => id === "hq-a" ? delayed.promise : Promise.resolve(b));
    render(<HQTryOnPage />); fireEvent.click(await screen.findByRole("button", { name: /失败 hq-b/ }));
    expect(await screen.findByText("VRAM_OOM · 显存不足")).toBeVisible();
    await act(async () => delayed.resolve(a)); expect(screen.getByRole("heading", { name: "任务 hq-b" })).toBeVisible();
  });
});
