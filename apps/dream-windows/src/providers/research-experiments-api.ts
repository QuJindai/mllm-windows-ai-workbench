import { validComparison, validFusionReplay } from "../domain/research-experiments";

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`/api/research/${path}`, { credentials: "same-origin", ...init });
  const data: unknown = await response.json();
  if (!response.ok) throw new Error(data && typeof data === "object" && "message" in data && typeof data.message === "string"
    ? data.message : `研究接口不可用（${response.status}）`);
  return data;
}

export const researchExperimentsApi = {
  async compare(left: string, right: string, signal?: AbortSignal) {
    const data = await request(`comparison?${new URLSearchParams({ left, right })}`, { signal });
    if (!validComparison(data) || data.provenance.left.runId !== left || data.provenance.right.runId !== right)
      throw new Error("比较指标或来源无效，未显示对照结果");
    return data;
  },
  async capability(signal?: AbortSignal) {
    const data = await request("fusion/capability", { signal });
    if (!data || typeof data !== "object" || !("available" in data) || data.available !== true
      || !("execution" in data) || data.execution !== "cpu-import-replay"
      || !("nativeGenerationAvailable" in data) || data.nativeGenerationAvailable !== false)
      throw new Error("CPU 预测重放能力不可用");
    return true;
  },
  async replay(json: string, signal?: AbortSignal) {
    const data = await request("fusion/replay", { method: "POST", headers: { "Content-Type": "application/json" }, body: json, signal });
    if (!validFusionReplay(data)) throw new Error("预测融合指标或来源无效，未显示结果");
    return data;
  },
};
