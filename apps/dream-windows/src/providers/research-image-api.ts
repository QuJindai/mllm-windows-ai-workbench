export const imageModes = ["first_only", "equal_mean", "token_weighted", "anchor_residual"] as const;
export type ImageMode = typeof imageModes[number];
export const imageModeLabels: Record<ImageMode, string> = { first_only: "仅首块", equal_mean: "等权均值", token_weighted: "有效 token 加权", anchor_residual: "锚点残差" };
export type ImageSettings = { modelId: "realistic-vision-v5.1-fusion"; prompt: string; negativePrompt: string; seed: number; steps: number; cfg: number; alpha: number; width: number; height: number; requestId: string };
export type ImageJob = { id: string; state: "queued" | "running" | "cancelling" | "complete" | "cancelled" | "failed"; settings: ImageSettings; progress: number; message: string; error: string | null;
  result: null | { contractVersion: string; jobId: string; settingsSha256: string;
    provenance: { engine: string; scheduler: string; predictionType: string; settings: ImageSettings; modelSha256: string; pipelineConfigSha256: string; initialLatentSha256: string; engineRevision: string; torchVersion: string; diffusersVersion: string; nativeDeviceParity: false; negativeEncodingPerformed: boolean;
      chunkCounts: Array<{ positive: number; negative: number }>; encodedTokenIds: Array<{ positive: number[]; negative: number[] }> };
    variants: Array<{ mode: ImageMode; imageUrl: string; imageSha256: string; effectiveWeights: number[]; durationMs: number }> } };
const base = "/api/identity/research/images";
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const integer = (v: unknown, min: number, max: number): v is number => finite(v) && Number.isInteger(v) && v >= min && v <= max;
export const activeImageJob = (job: ImageJob | null) => !!job && ["queued", "running", "cancelling"].includes(job.state);
export const validImageJobId = (id: string) => /^fusion-[a-f0-9]{24}$/.test(id);

function validSettings(s: unknown): s is ImageSettings {
  return object(s) && s.modelId === "realistic-vision-v5.1-fusion" && typeof s.prompt === "string" && /\S/.test(s.prompt) && s.prompt.length <= 2000
    && typeof s.negativePrompt === "string" && s.negativePrompt.length <= 2000 && integer(s.seed, 0, 2147483647) && integer(s.steps, 1, 30)
    && finite(s.cfg) && s.cfg >= 1 && s.cfg <= 15 && finite(s.alpha) && s.alpha >= 0 && s.alpha <= 1
    && integer(s.width, 256, 512) && s.width % 64 === 0 && integer(s.height, 256, 512) && s.height % 64 === 0
    && typeof s.requestId === "string" && /^[A-Za-z0-9_-]{16,80}$/.test(s.requestId);
}
function sameSettings(a: ImageSettings, b: ImageSettings) {
  return (Object.keys(a) as Array<keyof ImageSettings>).every(k => a[k] === b[k]);
}
export function validImageJob(v: unknown): v is ImageJob {
  if (!object(v) || typeof v.id !== "string" || !validImageJobId(v.id) || !validSettings(v.settings)
    || !["queued", "running", "cancelling", "complete", "cancelled", "failed"].includes(String(v.state))
    || !finite(v.progress) || v.progress < 0 || v.progress > 100 || typeof v.message !== "string"
    || (v.error !== null && typeof v.error !== "string")) return false;
  if (v.state !== "complete") return v.result === null;
  const settings = v.settings;
  const r = v.result;
  if (!object(r) || r.contractVersion !== "diffusers-chunk-fusion-images-v1" || r.jobId !== v.id || !hash(r.settingsSha256) || !object(r.provenance)) return false;
  const p = r.provenance;
  if (p.engine !== "diffusers-sd15-paired-chunk-cfg" || p.nativeDeviceParity !== false || p.scheduler !== "EulerDiscreteScheduler" || p.predictionType !== "epsilon"
    || !validSettings(p.settings) || !sameSettings(p.settings, v.settings) || p.negativeEncodingPerformed !== (v.settings.cfg !== 1)
    || ![p.modelSha256, p.pipelineConfigSha256, p.initialLatentSha256, p.engineRevision].every(hash)
    || ![p.torchVersion, p.diffusersVersion].every(s => typeof s === "string" && s.length > 0)
    || !Array.isArray(p.chunkCounts) || p.chunkCounts.length < 1 || p.chunkCounts.length > 4
    || !p.chunkCounts.every(c => object(c) && integer(c.positive, 0, 75) && integer(c.negative, 0, 75))
    || !Array.isArray(p.encodedTokenIds) || p.encodedTokenIds.length !== p.chunkCounts.length
    || !p.encodedTokenIds.every(c => object(c) && [c.positive, c.negative].every(ids => Array.isArray(ids) && ids.length === 77 && ids.every(id => integer(id, 0, 100000))))) return false;
  const counts = p.chunkCounts.map(c => Math.max(1, c.positive, settings.cfg === 1 ? 0 : c.negative));
  const count = counts.length;
  return Array.isArray(r.variants) && r.variants.length === 4 && r.variants.every((variant, index) => {
    const mode = imageModes[index];
    const expected = mode === "first_only" ? counts.map((_, i) => i === 0 ? 1 : 0)
      : mode === "equal_mean" ? counts.map(() => 1 / count)
      : mode === "token_weighted" ? counts.map(n => n / counts.reduce((a, b) => a + b, 0))
      : count === 1 ? [1] : counts.map((n, i) => i === 0 ? 1 - settings.alpha : settings.alpha * n / counts.slice(1).reduce((a, b) => a + b, 0));
    return object(variant) && variant.mode === mode && variant.imageUrl === `${base}/${v.id}/${mode}/image` && hash(variant.imageSha256)
      && finite(variant.durationMs) && variant.durationMs >= 0 && Array.isArray(variant.effectiveWeights) && variant.effectiveWeights.length === count
      && variant.effectiveWeights.every((w, i) => finite(w) && Math.abs(w - expected[i]) < 1e-6);
  });
}
async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(base + path, { credentials: "same-origin", ...init });
  const data: unknown = await response.json();
  if (!response.ok) throw new Error(object(data) && typeof data.message === "string" ? data.message : `图像实验接口不可用（${response.status}）`);
  return data;
}
function job(data: unknown, id?: string, settings?: ImageSettings) {
  if (!validImageJob(data) || (id && data.id !== id) || (settings && !sameSettings(data.settings, settings))) throw new Error("图像实验结果或来源无效，未显示图片");
  return data;
}
export const researchImageApi = {
  async capability(signal?: AbortSignal) {
    const data = await request("/capability", { signal });
    if (!object(data) || data.available !== true || data.engine !== "diffusers-sd15-paired-chunk-cfg" || data.deviceParity !== false)
      throw new Error(object(data) && typeof data.message === "string" ? data.message : "本地受控图像实验不可用");
  },
  async submit(settings: ImageSettings, signal?: AbortSignal) {
    return job(await request("", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings), signal }), undefined, settings);
  },
  async get(id: string, signal?: AbortSignal) {
    if (!validImageJobId(id)) throw new Error("图像实验编号无效");
    return job(await request(`/${id}`, { signal }), id);
  },
  async cancel(id: string, signal?: AbortSignal) {
    if (!validImageJobId(id)) throw new Error("图像实验编号无效");
    return job(await request(`/${id}/cancel`, { method: "POST", signal }), id);
  },
};
