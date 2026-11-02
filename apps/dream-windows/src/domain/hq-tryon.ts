import type { IdentityJob } from "./identity";

export type HQRole = "person" | "garment" | "pose";
export type HQJobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export interface HQParameters { seed: number; width: number; height: number; steps: number }
export interface HQIdentityOptions { profileId?: string | null; facePolish?: boolean; faceRestoreStrength?: number }
export interface HQAsset {
  id: string; label?: string; name?: string; category?: string; sha256?: string; fullSha256?: string;
  width?: number; height?: number;
}
export interface HQCatalog { items: HQAsset[]; total: number; hasMore: boolean; categories: string[] }
export interface HQStatus { configured: boolean; authorized: boolean; modelReady: boolean; pipeline?: string; error?: HQError }
export type HQError = string | { code?: string; message?: string } | null;
export interface HQInput extends HQAsset { role: HQRole; dimensions?: { width: number; height: number } }
export interface HQResult { sha256: string; width?: number; height?: number; mime?: string; metadata?: Record<string, unknown> }
export interface HQJob extends HQIdentityOptions {
  id: string; state: HQJobState; phase?: string; progress?: number; cancellationRequested?: boolean;
  pipeline?: string | null;
  inputs: HQInput[]; parameters?: HQParameters; idempotencyKey?: string; error?: HQError;
  createdAt?: string; updatedAt?: string; result?: HQResult | null; output?: HQResult | null;
  audit?: unknown; localAudit?: unknown;
  identityJobId?: string | null;
  identityResult?: IdentityJob["result"];
  requestedInputIds?: Record<HQRole, string>;
  historyDeleted?: boolean; resultDeleted?: boolean; refinementsAvailable?: boolean;
}
export interface HQCreateRequest extends HQIdentityOptions {
  personId: string; garmentId: string; poseId: string; idempotencyKey: string; parameters: HQParameters;
}
export const hqRoles: HQRole[] = ["person", "garment", "pose"];
export const hqRoleLabels: Record<HQRole, string> = { person: "人物", garment: "服装", pose: "姿势" };
export const hqStateLabels: Record<HQJobState, string> = {
  queued: "排队中", running: "运行中", succeeded: "已完成", failed: "失败", cancelled: "已取消",
};
export const hqActive = (job: HQJob) => job.state === "queued" || job.state === "running";
export const hqError = (error?: HQError) => typeof error === "string" ? error : [error?.code, error?.message].filter(Boolean).join(" · ");
export const defaultHQParameters: HQParameters = { seed: 0, width: 512, height: 768, steps: 24 };
export const hqResolutionPresets = [
  { width: 512, height: 768, label: "标准 512×768" },
  { width: 640, height: 960, label: "清晰 640×960" },
  { width: 768, height: 1152, label: "高清 768×1152" },
  { width: 768, height: 512, label: "标准横版 768×512" },
  { width: 960, height: 640, label: "清晰横版 960×640" },
  { width: 1152, height: 768, label: "高清横版 1152×768" },
] as const;
export const defaultHQIdentity = { facePolish: false, faceRestoreStrength: 0.35 };
export const hqExecutionBasis = "identity-session-hq-sd15-v1";
export function validHQParameters(p: HQParameters) {
  return Number.isInteger(p.seed) && p.seed >= 0 && p.seed <= 2147483647
    && [p.width, p.height].every(n => Number.isInteger(n) && n >= 256 && n <= 1152 && n % 64 === 0)
    && p.width * p.height <= 884736 && Number.isInteger(p.steps) && p.steps >= 1 && p.steps <= 50;
}
