import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IdentityPage } from "../../pages/IdentityPage";

const request = {
  referenceId: "ref-a", faceIndex: 0, prompt: "档案默认场景", negativePrompt: "模糊", seed: 42,
  width: 512, height: 768, steps: 28, cfg: 5.5, identityStrength: 0.82, structureStrength: 0.9, faceLoraStrength: 0.55,
};
const { referenceId: _referenceId, faceIndex: _faceIndex, ...defaults } = request;
const person = {
  id: "person-a", name: "小林", referenceId: "ref-a", faceIndex: 0,
  state: "ready" as "ready" | "preparing" | "failed" | "archived", defaults,
  featureKey: "private-feature-key", error: null as string | null, createdAt: "2026-09-20", updatedAt: "2026-09-20",
};
const complete = {
  id: "job-a", state: "complete" as "complete" | "queued", progress: 100, message: "生成完成", request,
  result: { imageUrl: "/api/outputs/job-a.png", metadata: { seed: 42, peakReservedMiB: 3379, cacheHit: true } }, error: null,
};
const laterJob = {
  ...complete, id: "job-b", request: { ...request, prompt: "第二张历史任务", seed: 73, steps: 36 },
  result: { imageUrl: "/api/outputs/job-b.png", metadata: { seed: 73, peakReservedMiB: 3379, cacheHit: true } },
};
const sampleBatch = {
  id: "batch-a", state: "sampling" as "sampling" | "queued" | "preparing" | "complete" | "cancelled" | "failed",
  request: { profileId: "person-a", request, count: 2, stepValues: [20, 28], previewEvery: 5 },
  items: [complete], currentItem: 2, totalItems: 4, completedItems: 1, step: 12, totalSteps: 28,
  progress: 36, stage: "采样", elapsedMs: 19800, etaMs: 25000 as number | null,
  previewUrl: "/api/identity/batches/batch-a/previews/job-b-step-10.png" as string | null,
  error: null as string | null, createdAt: "2026-09-20", updatedAt: "2026-09-20",
};
let profiles: typeof person[];
let batches: typeof sampleBatch[];
let jobs: typeof complete[];
let calls: Array<{ url: string; method: string; body: unknown }>;
let override: ((url: string, init?: RequestInit) => Promise<Response> | undefined) | undefined;
const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
function observeScrolling() {
  // jsdom has no layout/scroll implementation; leave real DOM focus behavior intact.
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
  return scroll;
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const posts = (url?: string) => calls.filter((call) => call.method === "POST" && (!url || call.url === url));

beforeEach(() => {
  localStorage.clear(); profiles = [structuredClone(person)]; batches = []; jobs = [structuredClone(complete)]; calls = []; override = undefined;
  // Real React page and API adapter; only the fetch boundary is replaced.
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    const delayed = override?.(url, init); if (delayed) return delayed;
    if (url === "/api/identity/status") return json({ ready: true, modelName: "Realistic Vision V5.1", message: "运行环境就绪", loras: [] });
    if (url === "/api/identity/references") return json([{ id: "ref-a", name: "合成参考.png", imageUrl: "/api/identity/references/ref-a/image", faces: [{ index: 0, box: [0, 0, 100, 100] }] }]);
    if (url === "/api/identity/jobs") return json(jobs);
    if (url.startsWith("/api/identity/jobs/")) {
      const job = jobs.find((item) => item.id === url.split("/")[4]);
      return job ? json(job) : json({ message: "任务不存在" }, 404);
    }
    if (url === "/api/identity/profiles" && method === "GET") return json(profiles.filter((p) => p.state !== "archived"));
    if (url === "/api/identity/profiles" && method === "POST") {
      const created = { ...person, ...body, id: "person-new", state: "preparing" as const }; profiles.push(created); return json(created);
    }
    if (url.startsWith("/api/identity/profiles/")) {
      const id = url.split("/")[4], profile = profiles.find((p) => p.id === id);
      if (!profile) return json({ message: "档案不存在" }, 404);
      if (url.endsWith("/archive")) { profile.state = "archived"; return json(profile); }
      if (url.endsWith("/rename")) { profile.name = body.name; return json(profile); }
      if (url.endsWith("/preset")) { profile.defaults = { ...defaults, steps: 20, seed: 42 }; return json(profile); }
      return json(profile);
    }
    if (url === "/api/identity/batches" && method === "GET") return json(batches);
    if (url === "/api/identity/batches" && method === "POST") {
      const value = { ...sampleBatch, state: "queued" as const, request: body, items: [], currentItem: 0, completedItems: 0, step: 0, previewUrl: null, etaMs: null };
      batches = [value]; return json(value);
    }
    if (url.startsWith("/api/identity/batches/")) {
      const batch = batches.find((b) => b.id === url.split("/")[4]);
      if (!batch) return json({ message: "批次不存在" }, 404);
      if (url.endsWith("/cancel")) batch.state = "cancelled";
      return json(batch);
    }
    throw new Error(`Unexpected fetch ${method} ${url}`);
  }));
});
afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (originalScrollIntoView) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScrollIntoView);
  else delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
});

it("does not assign an existing draft to a profile whose selection failed", async () => {
  profiles.push({ ...person, id: "person-b", name: "小周", defaults: { ...defaults, steps: 36 } });
  const first = await open(); await selectPerson();
  fireEvent.change(screen.getByLabelText("步数"), { target: { value: "24" } });
  override = url => url === "/api/identity/profiles/person-b" ? Promise.resolve(json({message:"temporarily offline"},503)) : undefined;
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-b" } });
  await screen.findByText(/无法打开人物档案/);
  first.unmount(); override = undefined;
  await open();
  expect(screen.getByLabelText("步数")).toHaveValue(36);
});

it("preserves a saved draft through a failed automatic restoration and a later successful reload", async () => {
  const first = await open(); await selectPerson();
  fireEvent.change(screen.getByLabelText("步数"), { target: { value: "24" } });
  first.unmount();
  override = url => url === "/api/identity/profiles/person-a" ? Promise.resolve(json({message:"offline"},503)) : undefined;
  const failed = await open();
  await screen.findByText(/无法打开人物档案/);
  failed.unmount(); override = undefined;
  await open();
  expect(screen.getByLabelText("步数")).toHaveValue(24);
});

it("does not mark generation parameters dirty when only editing the profile name", async () => {
  const first = await open(); await selectPerson();
  fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "改名草稿" } });
  first.unmount(); profiles[0].defaults = { ...defaults, steps: 36 };
  await open();
  expect(screen.getByLabelText("步数")).toHaveValue(36);
});

it("preserves the displayed research defaults of an unsent draft over a changed server preset", async () => {
  const first = await open(); await selectPerson();
  fireEvent.change(screen.getByLabelText("步数"), { target: { value: "24" } });
  first.unmount();
  Object.assign(profiles[0].defaults, { traceLevel: "h7", researchCoverage: "extended" });
  await open();
  expect(screen.getByLabelText("人物显微镜采集")).toHaveValue("off");
  fireEvent.change(screen.getByLabelText("人物显微镜采集"), { target: { value: "h7" } });
  expect(screen.getByLabelText("研究采集范围")).toHaveValue("representative");
});

it("restores an unsent profile draft on refresh without saving it into the profile", async () => {
  const first = await open(); await selectPerson();
  fireEvent.change(screen.getByLabelText("步数"), { target: { value: "24" } });
  fireEvent.change(screen.getByLabelText("生成张数"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("场景提示词"), { target: { value: "未提交的新场景" } });
  first.unmount();
  await open();
  await waitFor(() => expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a"));
  expect(screen.getByLabelText("步数")).toHaveValue(24);
  expect(screen.getByLabelText("生成张数")).toHaveValue(3);
  expect(screen.getByLabelText("场景提示词")).toHaveValue("未提交的新场景");
  expect(profiles[0].defaults.steps).toBe(28);
  expect(posts()).toHaveLength(0);
});

async function open() {
  const view = render(<StrictMode><IdentityPage /></StrictMode>);
  await screen.findByText("Realistic Vision V5.1");
  await waitFor(() => expect(screen.getByLabelText("选择人物档案")).toBeEnabled());
  return view;
}
async function selectPerson(id = "person-a") {
  fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: id } });
  await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue(profiles.find((p) => p.id === id)!.defaults.prompt));
}

describe("named profiles and serial batches through HTTP", () => {
  it("starts a separate new person without reusing or modifying the selected person's reference", async () => {
    await open(); await selectPerson();
    expect(screen.getByLabelText("上传参考照")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "新建人物" }));
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("");
    expect(screen.getByLabelText("档案名称")).toHaveValue("");
    expect(screen.getByLabelText("选择参考照")).toHaveValue("");
    expect(screen.queryByRole("radio", { name: "人脸 1" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("上传参考照")).toBeEnabled();
    expect(screen.getByLabelText("上传参考照")).toHaveFocus();
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "另一个人物" } });
    expect(screen.getByRole("button", { name: "创建人物档案" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    expect(screen.getByRole("option", { name: "小林 · FaceID · 可使用" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开人物任务 job-a" })).toBeInTheDocument();
    expect(posts()).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("选择参考照"), { target: { value: "ref-a" } });
    fireEvent.click(screen.getByRole("button", { name: "创建人物档案" }));
    await waitFor(() => expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-new"));
    expect(posts()).toEqual([{ url: "/api/identity/profiles", method: "POST", body: { name: "另一个人物", referenceId: "ref-a", faceIndex: 0 } }]);
    expect(screen.getByRole("option", { name: "小林 · FaceID · 可使用" })).toBeInTheDocument();
  });

  it("can restart a temporary person's draft and resets inherited generation options", async () => {
    await open(); await selectPerson();
    fireEvent.click(screen.getByRole("button", { name: "新建人物" }));
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "未提交的人物" } });
    fireEvent.change(screen.getByLabelText("选择参考照"), { target: { value: "ref-a" } });
    fireEvent.change(screen.getByLabelText("步数"), { target: { value: "36" } });
    fireEvent.click(screen.getByRole("button", { name: "新建人物" }));
    expect(screen.getByLabelText("档案名称")).toHaveValue("");
    expect(screen.getByLabelText("选择参考照")).toHaveValue("");
    expect(screen.getByLabelText("种子")).toHaveValue("random");
    expect(screen.getByRole("button", { name: "创建人物档案" })).toBeDisabled();
    expect(screen.getByLabelText("上传参考照")).toHaveFocus();
    expect(posts()).toHaveLength(0);
  });

  it("cannot start a new person while a batch is running", async () => {
    batches = [structuredClone(sampleBatch)];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    await screen.findByRole("status", { name: "批次进度" });
    expect(screen.getByRole("button", { name: "新建人物" })).toBeDisabled();
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a");
    expect(posts()).toHaveLength(0);
  });

  it.each([
    { state: "complete", etaMs: 0, expected: "预计剩余：已完成" },
    { state: "complete", etaMs: null, expected: "预计剩余：已完成" },
    { state: "cancelled", etaMs: 0, expected: "预计剩余：已停止（已取消）" },
    { state: "failed", etaMs: 25000, expected: "预计剩余：已停止（失败）" },
    { state: "sampling", etaMs: 0, expected: "预计剩余：0.0 秒（估计）" },
    { state: "sampling", etaMs: null, expected: "预计剩余：暂无可靠估计" },
  ] as const)("distinguishes terminal status from a running ETA, including zero ($state, $etaMs)", async ({ state, etaMs, expected }) => {
    batches = [{ ...structuredClone(sampleBatch), state, etaMs }];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    await screen.findByRole("status", { name: "批次进度" });
    expect(screen.getByText(expected)).toBeVisible();
    expect(posts()).toHaveLength(0);
  });

  it("restores the latest viewed history job B instead of an older saved job A without submitting", async () => {
    jobs.push(structuredClone(laterJob));
    localStorage.setItem("dream.identity.last-job.v1", "job-a");
    const first = await open();
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-a" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-b" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    expect(localStorage.getItem("dream.identity.last-job.v1")).toBe("job-b");
    first.unmount();
    await open();
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("img", { name: "生成结果" })).toHaveAttribute("src", "/api/outputs/job-b.png");
    expect(screen.getByLabelText("步数")).toHaveValue(36);
    expect(screen.getByLabelText("种子")).toHaveValue("73");
    expect(posts()).toHaveLength(0);
  });

  it.each([{ faceIndex: 0, selected: "person-a" }, { faceIndex: 1, selected: "" }])("prioritizes a saved job over profile defaults and restores only its matching face binding ($faceIndex)", async ({ faceIndex, selected }) => {
    jobs.push(structuredClone(laterJob)); profiles[0].faceIndex = faceIndex;
    profiles[0].defaults = { ...defaults, steps: 20, seed: 999 };
    localStorage.setItem("dream.identity.selected-profile.v1", "person-a");
    localStorage.setItem("dream.identity.last-job.v1", "job-b");
    await open();
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByLabelText("选择人物档案")).toHaveValue(selected);
    expect(screen.getByLabelText("步数")).toHaveValue(36);
    expect(screen.getByLabelText("种子")).toHaveValue("73");
    const save = screen.getByRole("button", { name: "将 job-b 存为人物预设" });
    if (selected) expect(save).toBeEnabled(); else expect(save).toBeDisabled();
    expect(posts()).toHaveLength(0);
  });

  it("restores a job selected after a batch with its matching person, not the old batch or profile view", async () => {
    jobs.push(structuredClone(laterJob)); batches = [{ ...structuredClone(sampleBatch), state: "complete" }];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    const first = await open();
    await screen.findByRole("status", { name: "批次进度" });
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-b" }));
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("第二张历史任务"));
    expect(localStorage.getItem("dream.identity.last-batch.v1")).toBeNull();
    first.unmount();
    await open();
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.queryByRole("status", { name: "批次进度" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a");
    expect(screen.getByLabelText("步数")).toHaveValue(36);
    expect(posts()).toHaveLength(0);
  });

  it("restores an explicitly chosen profile after leaving a job, even if legacy saved job data remains", async () => {
    jobs.push(structuredClone(laterJob)); localStorage.setItem("dream.identity.last-job.v1", "job-b");
    const first = await open();
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    await selectPerson(); first.unmount();
    // The explicit last-view record must win over pre-upgrade compatibility keys.
    localStorage.setItem("dream.identity.last-job.v1", "job-b");
    await open();
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("档案默认场景"));
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a");
    expect(screen.getByLabelText("步数")).toHaveValue(28);
    expect(screen.queryByLabelText("当前任务状态")).not.toBeInTheDocument();
    expect(posts()).toHaveLength(0);
  });

  it("honors the explicit last job view over stale legacy batch data on reload", async () => {
    jobs.push(structuredClone(laterJob)); batches = [{ ...structuredClone(sampleBatch), state: "complete" }];
    const first = await open(); await selectPerson();
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-b" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    first.unmount(); localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    await open();
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-b" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a");
    expect(posts()).toHaveLength(0);
  });

  it("keeps a newer explicit profile selection when the old job's bound profile restoration finishes late", async () => {
    jobs.push(structuredClone(laterJob)); profiles.push({ ...person, id: "person-b", name: "小周", defaults: { ...defaults, prompt: "第二个人预设" } });
    localStorage.setItem("dream.identity.last-job.v1", "job-b");
    localStorage.setItem("dream.identity.selected-profile.v1", "person-a");
    let release!: (response: Response) => void;
    override = (url) => url === "/api/identity/profiles/person-a" ? new Promise((resolve) => { release = resolve; }) : undefined;
    const first = await open();
    await waitFor(() => expect(release).toBeTypeOf("function"));
    await selectPerson("person-b");
    await act(async () => release(json(person)));
    expect(screen.getByLabelText("场景提示词")).toHaveValue("第二个人预设");
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-b");
    first.unmount(); override = undefined;
    await open();
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("第二个人预设"));
    expect(posts()).toHaveLength(0);
  });

  it("does not restore an archived profile view created from a previously viewed history job", async () => {
    const first = await open();
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-a" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "打开人物任务 job-a" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "历史人物档案" } });
    fireEvent.click(screen.getByRole("button", { name: "创建人物档案" }));
    await waitFor(() => expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-new"));
    fireEvent.click(screen.getByRole("button", { name: "撤下人物档案" }));
    fireEvent.click(screen.getByRole("button", { name: "确认撤下" }));
    await waitFor(() => expect(screen.getByLabelText("选择人物档案")).toHaveValue(""));
    const writeCount = posts().length; first.unmount();
    await open();
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toBeEnabled());
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("");
    expect(screen.queryByLabelText("当前任务状态")).not.toBeInTheDocument();
    expect(posts()).toHaveLength(writeCount);
  });

  it("brings a newly accepted batch observation into view once without taking focus back on progress polls", async () => {
    const scroll = observeScrolling();
    await open(); await selectPerson();
    const generate = screen.getByRole("button", { name: "生成人物图像" });
    generate.focus();
    expect(scroll).not.toHaveBeenCalled();
    fireEvent.click(generate);
    const heading = await screen.findByRole("heading", { name: "批次观察" });
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
    expect(scroll.mock.instances[0]).toBe(heading);
    expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: "auto" });
    expect(heading).toHaveAttribute("tabindex", "-1");
    expect(heading).toHaveFocus();
    const cancel = screen.getByRole("button", { name: "取消批次" });
    cancel.focus();
    batches[0] = { ...batches[0], state: "sampling", step: 5, totalSteps: 28, elapsedMs: 5000 };
    await waitFor(() => expect(screen.getByText("5 / 28 步")).toBeVisible(), { timeout: 2500 });
    batches[0] = { ...batches[0], step: 10, elapsedMs: 9000 };
    await waitFor(() => expect(screen.getByText("10 / 28 步")).toBeVisible(), { timeout: 2500 });
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(cancel).toHaveFocus();
  });

  it("focuses observation once when opening each different saved batch", async () => {
    const scroll = observeScrolling();
    batches = [
      { ...structuredClone(sampleBatch), state: "complete" },
      { ...structuredClone(sampleBatch), id: "batch-b", state: "complete", request: { ...sampleBatch.request, request: { ...request, prompt: "第二批次" } } },
    ];
    await open();
    expect(scroll).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "打开人物批次 batch-a" }));
    await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { name: "批次观察" })).toHaveFocus();
    const next = screen.getByRole("button", { name: "打开人物批次 batch-b" });
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toBeEnabled());
    next.focus(); fireEvent.click(next);
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("第二批次"));
    await waitFor(() => {
      expect(scroll).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("heading", { name: "批次观察" })).toHaveFocus();
    });
  });

  it("does not steal focus if a pending batch is accepted after the page becomes hidden", async () => {
    const scroll = observeScrolling();
    let release!: (response: Response) => void;
    override = (url, init) => url === "/api/identity/batches" && init?.method === "POST" ? new Promise((resolve) => { release = resolve; }) : undefined;
    const view = render(<><button>其他页面操作</button><div hidden={false}><IdentityPage /></div></>);
    await screen.findByText("Realistic Vision V5.1"); await selectPerson();
    fireEvent.click(screen.getByRole("button", { name: "生成人物图像" }));
    await waitFor(() => expect(release).toBeTypeOf("function"));
    view.rerender(<><button>其他页面操作</button><div hidden><IdentityPage /></div></>);
    const other = screen.getByRole("button", { name: "其他页面操作" }); other.focus();
    await act(async () => release(json(sampleBatch)));
    expect(scroll).not.toHaveBeenCalled();
    expect(other).toHaveFocus();
  });

  it("creates one named profile, shows asynchronous preparation, then observes readiness without another POST", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("选择参考照"), { target: { value: "ref-a" } });
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "新人物" } });
    const create = screen.getByRole("button", { name: "创建人物档案" });
    fireEvent.click(create); fireEvent.click(create);
    expect(await screen.findByLabelText("人物档案状态")).toHaveTextContent("准备中");
    expect(screen.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    expect(posts("/api/identity/profiles")).toEqual([{ url: "/api/identity/profiles", method: "POST", body: { name: "新人物", referenceId: "ref-a", faceIndex: 0 } }]);
    profiles[1].state = "ready";
    await waitFor(() => expect(screen.getByLabelText("人物档案状态")).toHaveTextContent("可使用"), { timeout: 2500 });
    expect(localStorage.getItem("dream.identity.selected-profile.v1")).toBe("person-new");
    expect(JSON.stringify(localStorage)).not.toMatch(/private-feature-key|imageUrl|base64|embedding|合成参考/);
    expect(posts()).toHaveLength(1);
  });

  it("restores the saved profile and its server preset after remount with no submission", async () => {
    const first = await open(); await selectPerson();
    expect(screen.getByLabelText("种子")).toHaveValue("42");
    expect(screen.getByRole("radio", { name: "人脸 1" })).toBeChecked();
    first.unmount(); profiles[0].defaults = { ...defaults, steps: 36, prompt: "更新的预设" };
    await open();
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("更新的预设"));
    expect(screen.getByLabelText("步数")).toHaveValue(36);
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a");
    expect(posts()).toHaveLength(0);
  });

  it("isolates late profile reads from a newer selected person's defaults", async () => {
    profiles.push({ ...person, id: "person-b", name: "小周", defaults: { ...defaults, prompt: "第二个人" } });
    let release!: (response: Response) => void;
    override = (url) => url === "/api/identity/profiles/person-a" ? new Promise((resolve) => { release = resolve; }) : undefined;
    await open();
    fireEvent.change(screen.getByLabelText("选择人物档案"), { target: { value: "person-a" } });
    await waitFor(() => expect(release).toBeTypeOf("function"));
    await selectPerson("person-b");
    await act(async () => release(json(person)));
    expect(screen.getByLabelText("场景提示词")).toHaveValue("第二个人");
    expect(localStorage.getItem("dream.identity.selected-profile.v1")).toBe("person-b");
  });

  it("requires archive confirmation, explains retention, and exposes an in-use conflict without losing selection", async () => {
    await open(); await selectPerson();
    fireEvent.click(screen.getByRole("button", { name: "撤下人物档案" }));
    const dialog = screen.getByRole("dialog", { name: "确认撤下人物档案" });
    expect(dialog).toHaveTextContent("不删除参考照或历史结果");
    expect(dialog).toHaveTextContent("可恢复归档");
    fireEvent.click(within(dialog).getByRole("button", { name: "暂不撤下" }));
    expect(posts()).toHaveLength(0);
    override = (url) => url.endsWith("/archive") ? Promise.resolve(json({ message: "人物档案正在使用" }, 409)) : undefined;
    fireEvent.click(screen.getByRole("button", { name: "撤下人物档案" }));
    fireEvent.click(screen.getByRole("button", { name: "确认撤下" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("人物档案正在使用");
    expect(screen.getByLabelText("选择人物档案")).toHaveValue("person-a");
    override = undefined;
    fireEvent.click(screen.getByRole("button", { name: "确认撤下" }));
    await waitFor(() => expect(screen.getByLabelText("选择人物档案")).toHaveValue(""));
    expect(screen.queryByRole("option", { name: /小林/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开人物任务 job-a" })).toBeInTheDocument();
  });

  it("renames a profile through the frozen name-only endpoint", async () => {
    await open(); await selectPerson();
    fireEvent.change(screen.getByLabelText("档案名称"), { target: { value: "小林新名称" } });
    fireEvent.click(screen.getByRole("button", { name: "重命名人物档案" }));
    await screen.findByRole("option", { name: /小林新名称/ });
    expect(posts("/api/identity/profiles/person-a/rename")[0].body).toEqual({ name: "小林新名称" });
  });

  it("defaults to one image and sends a bounded step matrix without expanding seeds or old request fields", async () => {
    await open(); await selectPerson();
    expect(screen.getByLabelText("生成张数")).toHaveValue(1);
    expect(screen.getByLabelText("中间预览频率")).toHaveValue("0");
    fireEvent.change(screen.getByLabelText("生成张数"), { target: { value: "8" } });
    for (const steps of [20, 28, 36]) fireEvent.click(screen.getByRole("checkbox", { name: `${steps} 步` }));
    expect(screen.getByText(/最多 16 张/)).toBeVisible();
    expect(screen.getByRole("button", { name: "生成人物图像" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("生成张数"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "36 步" }));
    fireEvent.change(screen.getByLabelText("中间预览频率"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("种子"), { target: { value: "random" } });
    fireEvent.click(screen.getByRole("button", { name: "生成人物图像" }));
    await screen.findByRole("button", { name: "取消批次" });
    expect(posts("/api/identity/batches")).toHaveLength(1);
    expect(posts("/api/identity/batches")[0].body).toEqual({ profileId: "person-a", request: { ...request, modelId: "realistic-vision-v5.1-faceid", seed: "random", facePolish: false, faceRestoreStrength: 1 }, count: 2, stepValues: [20, 28], previewEvery: 5 });
    expect(posts("/api/identity/generate")).toHaveLength(0);
    expect(screen.getByLabelText("选择人物档案")).toBeDisabled();
    expect(screen.getByLabelText("生成张数")).toBeDisabled();
    expect(screen.getByLabelText("选择参考照")).toBeDisabled();
  });

  it("restores a running batch's true step, elapsed time and estimated ETA with no duplicate POST", async () => {
    batches = [structuredClone(sampleBatch)];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    localStorage.setItem("dream.identity.selected-profile.v1", "person-a");
    localStorage.setItem("dream.identity.text-draft.v1", JSON.stringify({ prompt: "其他草稿", negativePrompt: "" }));
    render(<StrictMode><IdentityPage /></StrictMode>);
    expect(await screen.findByRole("status", { name: "批次进度" })).toHaveTextContent("第 2 / 4 张");
    expect(screen.getByText("12 / 28 步")).toBeVisible();
    expect(screen.getByText("已用时间：19.8 秒（实测）")).toBeVisible();
    expect(screen.getByText("预计剩余：25.0 秒（估计）")).toBeVisible();
    expect(screen.getByAltText("采样中间预览")).toHaveAttribute("src", sampleBatch.previewUrl);
    expect(screen.getByText("采样中间预览（去噪预测，非最终成图）")).toBeVisible();
    expect(screen.getByLabelText("场景提示词")).toHaveValue(request.prompt);
    expect(screen.getByLabelText("场景提示词")).toBeDisabled();
    expect(screen.getByLabelText("生成张数")).toHaveValue(2);
    expect(screen.getByRole("checkbox", { name: "20 步" })).toBeChecked();
    expect(posts()).toHaveLength(0);
  });

  it("keeps completed cards and original links when cancelling the unfinished remainder", async () => {
    batches = [structuredClone(sampleBatch)]; localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    const results = await screen.findByRole("region", { name: "已完成结果" });
    const image = within(results).getByRole("img", { name: "生成结果" });
    expect(image.closest("a")).toHaveAttribute("href", complete.result.imageUrl);
    fireEvent.click(screen.getByRole("button", { name: "取消批次" }));
    await waitFor(() => expect(screen.getByRole("status", { name: "批次进度" })).toHaveTextContent("已取消"));
    expect(within(results).getByRole("img", { name: "生成结果" })).toBe(image);
    expect(posts("/api/identity/batches/batch-a/cancel")).toHaveLength(1);
    expect(screen.getByText(/已完成结果保留/)).toBeVisible();
  });

  it("saves a chosen completed result as the matching profile preset without resubmitting or changing identity", async () => {
    batches = [{ ...structuredClone(sampleBatch), state: "complete", etaMs: null }];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    const save = await screen.findByRole("button", { name: "将 job-a 存为人物预设" });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save); fireEvent.click(save);
    expect(await screen.findByText("已保存人物预设，不改变身份特征。")).toBeVisible();
    expect(posts()).toEqual([{ url: "/api/identity/profiles/person-a/preset", method: "POST", body: { jobId: "job-a" } }]);
    expect(JSON.stringify(localStorage)).not.toMatch(/private-feature-key|metadata|imageUrl/);
  });

  it("does not let an older batch read overwrite a newer selected batch", async () => {
    batches = [
      { ...structuredClone(sampleBatch), state: "complete" },
      { ...structuredClone(sampleBatch), id: "batch-b", state: "complete", request: { ...sampleBatch.request, request: { ...request, prompt: "第二批次" } } },
    ];
    let release!: (response: Response) => void;
    override = (url) => url === "/api/identity/batches/batch-a" ? new Promise((resolve) => { release = resolve; }) : undefined;
    await open();
    fireEvent.click(screen.getByRole("button", { name: "打开人物批次 batch-a" }));
    fireEvent.click(screen.getByRole("button", { name: "打开人物批次 batch-b" }));
    await waitFor(() => expect(screen.getByLabelText("场景提示词")).toHaveValue("第二批次"));
    await act(async () => release(json(batches[0])));
    expect(screen.getByLabelText("场景提示词")).toHaveValue("第二批次");
    expect(localStorage.getItem("dream.identity.last-batch.v1")).toBe("batch-b");
  });

  it("can save an already completed item while the remaining batch continues with frozen parameters", async () => {
    batches = [structuredClone(sampleBatch)]; localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    const save = await screen.findByRole("button", { name: "将 job-a 存为人物预设" });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);
    expect(await screen.findByText("已保存人物预设，不改变身份特征。")).toBeVisible();
    expect(posts("/api/identity/profiles/person-a/preset")[0].body).toEqual({ jobId: "job-a" });
    expect(screen.getByLabelText("步数")).toHaveValue(28);
    expect(screen.getByRole("button", { name: "取消批次" })).toBeEnabled();
  });

  it("keeps an explicitly chosen matching profile when opening a legacy completed job to save its preset", async () => {
    await open(); await selectPerson();
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-a" }));
    const save = await screen.findByRole("button", { name: "将 job-a 存为人物预设" });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);
    expect(await screen.findByText("已保存人物预设，不改变身份特征。")).toBeVisible();
    expect(posts("/api/identity/profiles/person-a/preset")[0].body).toEqual({ jobId: "job-a" });
  });

  it("does not offer another person's completed job as a selected profile's preset", async () => {
    await open(); await selectPerson();
    override = (url) => url === "/api/identity/jobs/job-a" ? Promise.resolve(json({ ...complete, request: { ...request, faceIndex: 1 } })) : undefined;
    fireEvent.click(screen.getByRole("button", { name: "打开人物任务 job-a" }));
    expect(await screen.findByRole("button", { name: "将 job-a 存为人物预设" })).toBeDisabled();
    expect(posts()).toHaveLength(0);
  });

  it("polls real stage changes without inventing sampling steps, preview or ETA while loading", async () => {
    batches = [{ ...structuredClone(sampleBatch), state: "preparing", stage: "加载模型", step: 0, currentItem: 0, previewUrl: null, etaMs: null }];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    expect(await screen.findByText("当前阶段：加载模型")).toBeVisible();
    expect(screen.queryByText("12 / 28 步")).not.toBeInTheDocument();
    expect(screen.getByText("预计剩余：暂无可靠估计")).toBeVisible();
    expect(screen.queryByAltText("采样中间预览")).not.toBeInTheDocument();
    batches[0] = structuredClone(sampleBatch);
    await waitFor(() => expect(screen.getByText("12 / 28 步")).toBeVisible(), { timeout: 2500 });
    expect(screen.getByAltText("采样中间预览")).toHaveAttribute("src", sampleBatch.previewUrl);
    expect(posts()).toHaveLength(0);
  });

  it("restores interrupted batches with completed results and reports failure instead of restarting", async () => {
    batches = [{ ...structuredClone(sampleBatch), state: "failed", error: "服务重启，批次已中断" }];
    localStorage.setItem("dream.identity.last-batch.v1", "batch-a");
    render(<IdentityPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("服务重启，批次已中断");
    expect(within(screen.getByRole("region", { name: "已完成结果" })).getByRole("img", { name: "生成结果" })).toBeVisible();
    expect(screen.getByText("预计剩余：已停止（失败）")).toBeVisible();
    expect(posts()).toHaveLength(0);
  });
});
