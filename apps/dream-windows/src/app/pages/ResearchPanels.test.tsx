import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MicroscopePage } from "./MicroscopePage";
import { DreamProviderContext } from "../providers";
import { DreamHttpProvider } from "../../providers/DreamHttpProvider";
import { influenceArtifact, selfIndexArtifact, selfMapArtifact } from "../../test/research-artifacts";
import hardwareFixture from "../../fixtures/hardware.json";

afterEach(() => vi.unstubAllGlobals());
const missing = (runId: string, message = "当前运行未采集有效研究记录") => ({ available: false, runId, truth: "unavailable", message });
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
function setup(overrides: Record<string, unknown | (() => Promise<Response>)> = {}) {
  const traces = [
    { runId: "run-basic", hasAttention: false, hasLatent: true },
    { runId: "run-cross", hasAttention: true, hasLatent: true },
    { runId: "run-h6", hasAttention: false, hasLatent: true, hasInfluence: true },
    { runId: "run-self", hasAttention: false, hasLatent: true, hasInfluence: true, hasSelfAttention: true },
  ].map((entry, index) => ({ ...entry, totalTimeMs: 1000, modifiedAt: `2026-09-20T00:0${4 - index}:00Z`, truth: "observed" }));
  const routes: Record<string, unknown | (() => Promise<Response>)> = {
    "/api/hardware": hardwareFixture,
    "/api/capabilities": {},
    "/api/research/status": { available: false, truth: "unavailable", message: "研究引擎暂未部署" },
    "/api/traces": traces,
    "/api/traces/run-h6/influence": influenceArtifact,
    "/api/traces/run-self/self-attention": selfIndexArtifact,
    ...Object.fromEntries(selfIndexArtifact.maps.map((entry) => [entry.mapUrl, selfMapArtifact(entry.id)])),
    ...overrides,
  };
  const fetcher = vi.fn(async (path: string) => {
    if (path in routes) {
      const value = routes[path];
      return typeof value === "function" ? value() : response(value);
    }
    const trace = /^\/api\/traces\/([^/]+)$/.exec(path);
    if (trace) return response({ available: true, runId: trace[1] === "latest" ? "run-basic" : trace[1], truth: "observed", totalTimeMs: 1000, nodes: [], evidence: { cfg: 1 } });
    return response(missing(path.split("/")[3]));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<DreamProviderContext.Provider value={new DreamHttpProvider()}><MicroscopePage /></DreamProviderContext.Provider>);
  return fetcher;
}

describe("measured research panels", () => {
  it("labels identity attention as derived QK probabilities with actual coverage", async () => {
    setup({
      "/api/traces/run-self/self-attention": { ...selfIndexArtifact, source:"diffusers-unet" },
      ...Object.fromEntries(selfIndexArtifact.maps.map(entry => [entry.mapUrl, { ...selfMapArtifact(entry.id), source:"diffusers-unet" }]))
    });
    fireEvent.click(screen.getByRole("tab", { name: "H7 注意力" }));
    fireEvent.click(await screen.findByRole("tab", { name: /Self-attention/ }));
    fireEvent.click(await screen.findByRole("button", { name: "选择最近的H7自注意力记录" }));
    expect(await screen.findByText(/实测 Q\/K.*FP32 softmax/)).toBeVisible();
    expect(screen.queryByText(/最多 3 个代表层/)).not.toBeInTheDocument();
  });
  it("discovers H6 by hasInfluence, renders raw chunk metrics and switches sampled steps", async () => {
    const fetcher = setup();
    fireEvent.click(screen.getByRole("tab", { name: "条件影响" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择最近的H6条件影响记录" }));
    const map = await screen.findByRole("img", { name: /H6.*步骤 0.*分块 0/ });
    expect(map.querySelectorAll("[data-raw-value]")).toHaveLength(4);
    expect(map.querySelector("[data-raw-value='0.004']")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "分块原始指标" })).toHaveTextContent("0.125");
    expect(screen.getByRole("table", { name: "分块原始指标" })).toHaveTextContent("-0.2");
    expect(screen.getByText(/不代表 Windows 生产路径对分块预测取算术平均/)).toBeVisible();
    expect(screen.getByText(/额外.*研究.*前向/)).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "条件影响分块" }), { target: { value: "1" } });
    expect(screen.getByRole("img", { name: /H6.*分块 1/ }).querySelector("[data-raw-value='0.04']")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "条件影响分块" }), { target: { value: "0" } });
    fireEvent.change(screen.getByRole("combobox", { name: "条件影响步骤" }), { target: { value: "4" } });
    const zeroMap = screen.getByRole("img", { name: /H6.*步骤 4/ });
    expect([...zeroMap.querySelectorAll("[data-display-intensity]")].map((cell) => cell.getAttribute("data-display-intensity"))).toEqual(["0", "0", "0", "0"]);
    expect(screen.getByText(/CFG=1.*无无条件分支.*0/)).toBeVisible();
    expect(fetcher.mock.calls.filter(([path]) => path.endsWith("/influence")).map(([path]) => path)).toContain("/api/traces/run-h6/influence");
  });

  it("shows absent and invalid H6 records without maps, then refreshes the same run", async () => {
    const fetcher = setup({ "/api/traces/run-h6/influence": missing("run-h6", "条件影响采集文件缺失") });
    fireEvent.click(screen.getByRole("tab", { name: "条件影响" }));
    fireEvent.click(await screen.findByRole("button", { name: "选择最近的H6条件影响记录" }));
    expect(await screen.findByText("条件影响采集文件缺失")).toBeVisible();
    expect(screen.queryByRole("img", { name: /H6/ })).not.toBeInTheDocument();
    fetcher.mockImplementation(async (path: string) => response(path.endsWith("/influence") ? { ...influenceArtifact, totalChunks: 0 } : path === "/api/traces" ? [] : path === "/api/hardware" ? hardwareFixture : { available: true, runId: "run-h6", totalTimeMs: 1000, nodes: [] }));
    fireEvent.click(screen.getByRole("button", { name: "刷新记录" }));
    expect(await screen.findByText(/H6 条件影响记录无效/)).toBeVisible();
    expect(screen.queryByRole("img", { name: /H6/ })).not.toBeInTheDocument();
  });

  it("discovers self independently of cross and fetches only selected anchors", async () => {
    const fetcher = setup();
    fireEvent.click(screen.getByRole("tab", { name: "H7 注意力" }));
    fireEvent.click(await screen.findByRole("tab", { name: /Self-attention/ }));
    fireEvent.click(await screen.findByRole("button", { name: "选择最近的H7自注意力记录" }));
    const firstMap = await screen.findByRole("img", { name: /自注意力.*锚点 \(0, 0\).*步骤 0/ });
    expect(firstMap.querySelector("[data-raw-value='0.4']")).toBeInTheDocument();
    expect(screen.getByText(/原始.*softmax.*概率/)).toBeVisible();
    expect(fetcher.mock.calls.filter(([path]) => path.includes("/self-attention/maps/")).map(([path]) => path)).toEqual(["/api/traces/run-self/self-attention/maps/self-center"]);
    fireEvent.change(screen.getByRole("combobox", { name: "自注意力锚点" }), { target: { value: "3" } });
    const constantMap = await screen.findByRole("img", { name: /自注意力.*锚点 \(1, 1\).*步骤 0/ });
    expect([...constantMap.querySelectorAll("[data-raw-value]")].map((cell) => cell.getAttribute("data-raw-value"))).toEqual(["0.25", "0.25", "0.25", "0.25"]);
    fireEvent.change(screen.getByRole("combobox", { name: "自注意力步骤" }), { target: { value: "4" } });
    expect(await screen.findByRole("img", { name: /自注意力.*步骤 4/ })).toBeVisible();
    expect(screen.getByText("峰值概率 peak").parentElement).toHaveTextContent("0.7");
    expect(screen.getByRole("combobox", { name: "选择运行记录" })).toHaveValue("run-self");
  });

  it("rejects a self map that disagrees with its selected index descriptor", async () => {
    setup({ "/api/traces/run-self/self-attention/maps/self-center": { ...selfMapArtifact(), step: 1 } });
    fireEvent.click(screen.getByRole("tab", { name: "H7 注意力" }));
    fireEvent.click(await screen.findByRole("tab", { name: /Self-attention/ }));
    fireEvent.click(await screen.findByRole("button", { name: "选择最近的H7自注意力记录" }));
    expect(await screen.findByText(/空间图与所选索引不一致/)).toBeVisible();
    expect(screen.queryByRole("img", { name: /自注意力/ })).not.toBeInTheDocument();
  });

  it("clears self maps on run change and ignores a late response from the previous run", async () => {
    let resolveMap!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolveMap = resolve; });
    const fetcher = setup({ "/api/traces/run-self/self-attention/maps/self-center": () => pending });
    fireEvent.click(screen.getByRole("tab", { name: "H7 注意力" }));
    fireEvent.click(await screen.findByRole("tab", { name: /Self-attention/ }));
    fireEvent.click(await screen.findByRole("button", { name: "选择最近的H7自注意力记录" }));
    await waitFor(() => expect(fetcher.mock.calls.some(([path]) => path.endsWith("/maps/self-center"))).toBe(true));
    fireEvent.change(screen.getByRole("combobox", { name: "选择运行记录" }), { target: { value: "run-basic" } });
    await act(async () => { resolveMap(response(selfMapArtifact())); });
    expect(await screen.findByText("Self-attention 未采集")).toBeVisible();
    expect(screen.queryByRole("img", { name: /自注意力/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole("tabpanel", { name: "H7 注意力" })).queryByText("run-self")).not.toBeInTheDocument();
  });
});
