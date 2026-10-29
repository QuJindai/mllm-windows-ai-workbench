import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResearchImageExperiment } from "./ResearchImageExperiment";

const base = "/api/identity/research/images";
const id = "fusion-" + "a".repeat(24);
const modes = ["first_only", "equal_mean", "token_weighted", "anchor_residual"];
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const capability = { available: true, engine: "diffusers-sd15-paired-chunk-cfg", deviceParity: false };
const settings = { modelId: "realistic-vision-v5.1-fusion", prompt: "a mountain lake", negativePrompt: "", seed: 42, steps: 12, cfg: 5.5, alpha: .5, width: 512, height: 512, requestId: "test-request-id-0001" };
const row = (state = "queued", input = settings) => ({ id, state, settings: input, progress: state === "complete" ? 100 : 0, message: state, error: null, result: state !== "complete" ? null : {
  contractVersion: "diffusers-chunk-fusion-images-v1", jobId: id, settingsSha256: "a".repeat(64),
  provenance: { engine: "diffusers-sd15-paired-chunk-cfg", scheduler: "EulerDiscreteScheduler", predictionType: "epsilon", settings: input,
    modelSha256: "b".repeat(64), pipelineConfigSha256: "c".repeat(64), initialLatentSha256: "d".repeat(64), engineRevision: "e".repeat(64),
    torchVersion: "cpu-test", diffusersVersion: "fixture", nativeDeviceParity: false, negativeEncodingPerformed: true,
    chunkCounts: [{ positive: 3, negative: 0 }], encodedTokenIds: [{ positive: Array(77).fill(1), negative: Array(77).fill(2) }] },
  variants: modes.map(mode => ({ mode, imageUrl: `${base}/${id}/${mode}/image`, imageSha256: "f".repeat(64), effectiveWeights: [1], durationMs: 10 })),
} });
beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());
async function open() {
  render(<ResearchImageExperiment />);
  fireEvent.click(screen.getByRole("button", { name: "受控融合图像实验" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "生成四种融合图像" })).toBeEnabled());
}

it("submits the controlled experiment and polls bound real images with provenance", async () => {
  let submitted = settings;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("capability")) return response(capability);
    if (init?.method === "POST") { submitted = JSON.parse(String(init.body)); return response(row("queued", submitted)); }
    return response(row("complete", submitted));
  });
  vi.stubGlobal("fetch", fetch);
  await open();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("实验正向提示词"), { target: { value: "a mountain lake" } });
  fireEvent.click(screen.getByRole("button", { name: "生成四种融合图像" }));
  await waitFor(() => expect(screen.getAllByRole("img")).toHaveLength(4), { timeout: 2500 });
  expect(screen.getByRole("img", { name: "等权均值生成结果" })).toHaveAttribute("src", `${base}/${id}/equal_mean/image`);
  fireEvent.click(screen.getByText("实验来源与实际编码记录"));
  expect(screen.getByText("b".repeat(64))).toBeVisible();
  expect(screen.getByText(/不代表手机或 native 等价/)).toBeVisible();
  expect(submitted.requestId).toMatch(/^[a-zA-Z0-9_-]{16,80}$/);
  expect(submitted.prompt).toBe("a mountain lake");
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("cancels through the bound shared-queue API and never displays partial results", async () => {
  let submitted = settings;
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("capability")) return response(capability);
    if (url.endsWith("cancel")) return response(row("cancelled", submitted));
    if (init?.method === "POST") { submitted = JSON.parse(String(init.body)); return response(row("running", submitted)); }
    return response(row("running", submitted));
  });
  vi.stubGlobal("fetch", fetch);
  await open();
  fireEvent.click(screen.getByRole("button", { name: "生成四种融合图像" }));
  fireEvent.click(await screen.findByRole("button", { name: "取消图像实验" }));
  expect(await screen.findByText("已取消")).toBeVisible();
  expect(fetch).toHaveBeenCalledWith(`${base}/${id}/cancel`, expect.objectContaining({ method: "POST" }));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

it("rejects foreign image URLs and incomplete provenance from saved results", async () => {
  localStorage.setItem("dream.fusionImageJob", id);
  const forged = row("complete");
  forged.result!.variants[0].imageUrl = "https://foreign.invalid/image";
  vi.stubGlobal("fetch", vi.fn(async (url: string) => response(url.endsWith("capability") ? capability : forged)));
  render(<ResearchImageExperiment />);
  fireEvent.click(screen.getByRole("button", { name: "受控融合图像实验" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/来源无效/);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

it("reuses a request id after an uncertain submit so retries cannot launch duplicate GPU work", async () => {
  const submitted: typeof settings[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("capability")) return response(capability);
    const input = JSON.parse(String(init?.body)); submitted.push(input);
    if (submitted.length === 1) throw new Error("连接中断");
    return response(row("cancelled", input));
  }));
  await open();
  fireEvent.click(screen.getByRole("button", { name: "生成四种融合图像" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("连接中断");
  fireEvent.click(screen.getByRole("button", { name: "生成四种融合图像" }));
  await screen.findByText("已取消");
  expect(submitted[0].requestId).toBe(submitted[1].requestId);
});

it.each(["network-error","in-flight"])("keeps an uncertain NEW payload and UUID across collapse despite an OLD saved job (%s)", async interruption => {
  localStorage.setItem("dream.fusionImageJob",id);
  const submitted: typeof settings[]=[];
  let finishFirst: ((value: Response) => void) | undefined;
  const fetch=vi.fn(async (url: string,init?: RequestInit) => {
    if (url.endsWith("capability")) return response(capability);
    if (init?.method==="POST") {
      const value=JSON.parse(String(init.body)); submitted.push(value);
      if (submitted.length===1) {
        if (interruption==="network-error") throw new Error("提交结果未知");
        return new Promise<Response>(resolve => { finishFirst=resolve; });
      }
      return response(row("cancelled",value));
    }
    return response(row("complete",settings));
  });
  vi.stubGlobal("fetch",fetch);
  await open();
  fireEvent.change(screen.getByLabelText("实验正向提示词"),{target:{value:"NEW pending prompt"}});
  fireEvent.change(screen.getByLabelText("实验种子"),{target:{value:"1234"}});
  fireEvent.click(screen.getByRole("button",{name:"生成四种融合图像"}));
  if (interruption==="network-error") await screen.findByRole("alert");
  else expect(submitted).toHaveLength(1);
  const toggle=screen.getByRole("button",{name:"受控融合图像实验"});
  fireEvent.click(toggle);fireEvent.click(toggle);
  await waitFor(() => expect(screen.getByRole("button",{name:"生成四种融合图像"})).toBeEnabled());
  expect(screen.getByLabelText("实验正向提示词")).toHaveValue("NEW pending prompt");
  expect(screen.getByLabelText("实验种子")).toHaveValue(1234);
  fireEvent.click(screen.getByRole("button",{name:"生成四种融合图像"}));
  await screen.findByText("已取消");
  expect(submitted[1]).toEqual(submitted[0]);
  if (finishFirst) {
    await act(async () => { finishFirst!(response(row("queued",submitted[0]))); });
    expect(screen.getByText("已取消")).toBeVisible();
    expect(screen.queryByText("排队中")).not.toBeInTheDocument();
  }
});

it("retries failed images explicitly and clears failures after a validated reread", async () => {
  localStorage.setItem("dream.fusionImageJob",id);
  const fetch=vi.fn(async (url: string,_init?: RequestInit) => response(url.endsWith("capability")?capability:row("complete")));
  vi.stubGlobal("fetch",fetch);
  await open();
  const label="等权均值生成结果";
  fireEvent.error(screen.getByRole("img",{name:label}));
  expect(screen.queryByRole("img",{name:label})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"重试等权均值图片"}));
  expect(screen.getByRole("img",{name:label})).toHaveAttribute("src",`${base}/${id}/equal_mean/image`);
  fireEvent.error(screen.getByRole("img",{name:label}));
  const toggle=screen.getByRole("button",{name:"受控融合图像实验"});
  fireEvent.click(toggle);fireEvent.click(toggle);
  expect(await screen.findByRole("img",{name:label})).toBeVisible();
  expect(fetch.mock.calls.every(call => call.length===1 || (call[1] as RequestInit)?.method!=="POST")).toBe(true);
});
