export type ComparisonProvenance = {
  runId: string; modelId: string; backend: string; samplingMethod: string; scheduler: string;
  steps: number; cfg: number; source: string; metricSource: string; recordSha256: string;
};
export type RunComparison = {
  contractVersion: "latent-run-comparison-v1"; truth: "derived";
  scope: "descriptive-recorded-latent-statistics";
  coverage: { capturedSteps: number[]; capturedCount: number; configuredSteps: number };
  provenance: { left: ComparisonProvenance; right: ComparisonProvenance };
  rows: Array<{ step: number; metric: "mean" | "std" | "l2"; left: number; right: number; delta: number }>;
  limitations: string;
};
export type FusionReplay = {
  contractVersion: "mobile-chunk-fusion-replay-v1"; truth: "derived"; execution: "cpu-import-replay";
  shape: number[]; cfg: number; alpha: number; chunkCount: number; skippedUnconditional: boolean;
  provenance: { runId: string; modelId: string; engine: string; engineRevision: string; step: number;
    capturedAt: string; inputSha256: string; inputVerification: "imported-unverified" };
  variants: Array<{ mode: string; weights: number[]; prediction: number[]; meanAbs: number; l2: number;
    deltaL2FromEqualMean: number; cosineToEqualMean: number | null }>;
};

type ObjectValue = Record<string, unknown>;
const object = (value: unknown): value is ObjectValue => !!value && typeof value === "object" && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const text = (value: unknown) => typeof value === "string" && value.trim().length > 0;

export function validComparison(value: unknown): value is RunComparison {
  if (!object(value) || value.contractVersion !== "latent-run-comparison-v1" || value.truth !== "derived"
    || value.scope !== "descriptive-recorded-latent-statistics" || !object(value.coverage) || !object(value.provenance)) return false;
  const { capturedSteps, capturedCount, configuredSteps } = value.coverage;
  if (!Array.isArray(capturedSteps) || !capturedSteps.length || capturedSteps.length !== capturedCount
    || !Number.isInteger(configuredSteps) || !finite(configuredSteps) || configuredSteps < 1 || configuredSteps > 50
    || !capturedSteps.every(s => Number.isInteger(s) && s >= 0 && s <= configuredSteps)
    || new Set(capturedSteps).size !== capturedSteps.length) return false;
  for (const source of [value.provenance.left, value.provenance.right]) {
    if (!object(source) || !hash(source.recordSha256) || !finite(source.cfg)
      || source.steps !== configuredSteps || !["runId", "modelId", "backend", "samplingMethod", "scheduler", "source", "metricSource"].every(k => text(source[k]))) return false;
  }
  const left = value.provenance.left as ObjectValue, right = value.provenance.right as ObjectValue;
  if (left.runId === right.runId || ["modelId", "backend", "samplingMethod", "scheduler", "steps", "cfg", "metricSource"]
    .some(key => left[key] !== right[key])) return false;
  if (!Array.isArray(value.rows) || value.rows.length !== capturedSteps.length * 3) return false;
  const keys = new Set<string>();
  for (const row of value.rows) {
    if (!object(row) || !capturedSteps.includes(row.step) || !["mean", "std", "l2"].includes(String(row.metric))
      || !finite(row.left) || !finite(row.right) || !finite(row.delta)
      || Math.abs(row.delta - (row.right - row.left)) > 1e-9 * Math.max(1, Math.abs(row.delta))) return false;
    keys.add(`${row.step}/${row.metric}`);
  }
  return keys.size === value.rows.length && text(value.limitations);
}

export function validFusionReplay(value: unknown): value is FusionReplay {
  if (!object(value) || value.contractVersion !== "mobile-chunk-fusion-replay-v1" || value.truth !== "derived"
    || value.execution !== "cpu-import-replay" || !object(value.provenance)
    || value.provenance.inputVerification !== "imported-unverified" || !hash(value.provenance.inputSha256)
    || !["runId", "modelId", "engine", "engineRevision", "capturedAt"].every(k => text((value.provenance as ObjectValue)[k]))
    || !Number.isInteger(value.provenance.step) || !finite(value.cfg) || !finite(value.alpha)
    || !Number.isInteger(value.chunkCount) || !finite(value.chunkCount) || value.chunkCount < 1 || value.chunkCount > 4
    || !Array.isArray(value.shape) || !value.shape.length || !value.shape.every(v => Number.isInteger(v) && v > 0)
    || !Array.isArray(value.variants) || value.variants.length !== 4) return false;
  const elements = value.shape.reduce((a: number, b: number) => a*b, 1);
  if (elements > 65536) return false;
  const modes = ["first_only", "equal_mean", "token_weighted", "anchor_residual"];
  return value.variants.every((variant, index) => object(variant) && variant.mode === modes[index]
    && Array.isArray(variant.weights) && variant.weights.length === value.chunkCount && variant.weights.every(finite)
    && Array.isArray(variant.prediction) && variant.prediction.length === elements && variant.prediction.every(finite)
    && finite(variant.meanAbs) && finite(variant.l2) && finite(variant.deltaL2FromEqualMean)
    && (variant.cosineToEqualMean === null || finite(variant.cosineToEqualMean)));
}
