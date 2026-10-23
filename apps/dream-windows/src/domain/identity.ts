export const IDENTITY_MODEL_ID = "realistic-vision-v5.1-faceid";
export const ILLUSTRIOUS_IDENTITY_MODEL_ID = "illustrious-xl-v2.0-faceid";
export const VISUAL_REFERENCE_MODEL_ID = "cyberrealistic-xl-plus-face";
export const ILLUSTRIOUS_VISUAL_MODEL_ID = "illustrious-xl-v2.0-plus-face";
export type ReferenceKind = "faceid" | "visual";
export function identityReferenceKind(modelId?: string): ReferenceKind { return modelId === VISUAL_REFERENCE_MODEL_ID || modelId === ILLUSTRIOUS_VISUAL_MODEL_ID ? "visual" : "faceid"; }
export function isIdentityModelId(id: string) { return id === IDENTITY_MODEL_ID || id === ILLUSTRIOUS_IDENTITY_MODEL_ID || identityReferenceKind(id) === "visual"; }
export function identityModelName(id?: string) {
  if (id === ILLUSTRIOUS_VISUAL_MODEL_ID) return "Illustrious XL v2.0 + Plus Face（动漫视觉参考）";
  if (id === VISUAL_REFERENCE_MODEL_ID) return "CyberRealistic XL + Plus Face（动漫视觉参考）";
  return id === ILLUSTRIOUS_IDENTITY_MODEL_ID ? "Illustrious XL v2.0 + FaceID Plus V2 SDXL" : "Realistic Vision V5.1 + FaceID Plus V2";
}
export type IdentityModel = {
  id: string; name: string; architecture: "SD1.5" | "SDXL";
  referenceKind?: ReferenceKind;
  ready: boolean; message: string; loras: Array<{ id: string; name: string }>;
};

export type IdentityStatus = {
  ready: boolean;
  modelName: string;
  message: string;
  loras: Array<{ id: string; name: string }>;
  models?: IdentityModel[];
  facePolish?: { ready: boolean; message: string };
  animePolish?: { ready: boolean; message: string };
  visualPolish?: { ready: boolean; message: string };
};

export type IdentityReference = {
  id: string;
  referenceKind?: ReferenceKind;
  name: string;
  imageUrl: string;
  faces: Array<{ index: number; box: number[] }>;
};

export type IdentityRequest = {
  modelId?: string;
  referenceId: string;
  faceIndex: number;
  prompt: string;
  negativePrompt: string;
  seed: number | "random";
  width: number;
  height: number;
  steps: number;
  cfg: number;
  identityStrength: number;
  referenceStart?: number;
  referenceEnd?: number;
  structureStrength: number;
  faceLoraStrength: number;
  facePolish: boolean;
  faceRestoreStrength: number;
  animeProfileId?: string | null;
  animeDenoiseStrength?: number;
  visualPolishPrompt?: string;
  visualPolishNegativePrompt?: string;
  traceLevel?: "off" | "basic" | "h6" | "h7";
  researchCoverage?: "representative" | "extended";
  loraId?: string;
  loraStrength?: number;
};

export type IdentityFacePolishResult = {
  enabled: boolean;
  status: "disabled" | "completed" | "failed";
  originalImageUrl?: string | null;
  message?: string | null;
  restoreStrength?: number;
  method?: "anime-reference-local-redraw" | "visual-reference-local-redraw";
  profileName?: string;
  profileId?: string;
  denoiseStrength?: number;
  referenceId?: string;
  faceIndex?: number;
  featureKey?: string;
  faceBox?: number[];
  cropBox?: number[];
  outsideMaskUnchanged?: boolean;
  restoreModel?: string;
  detailerVersion?: "masked-face-v1";
  processingSize?: number[];
  detailPrompt?: string;
  detailNegativePrompt?: string;
};

export type IdentityJob = {
  id: string;
  resultDeleted?: boolean;
  state: "queued" | "preparing" | "sampling" | "complete" | "failed" | "cancelled";
  progress: number;
  message: string;
  request: IdentityRequest;
  result: { imageUrl: string; metadata: Record<string, unknown> & { facePolish?: IdentityFacePolishResult; facePolishValidationError?: string } } | null;
  error: string | null;
};

export const identityStateLabels: Record<IdentityJob["state"], string> = {
  queued: "排队中", preparing: "准备中", sampling: "采样中",
  complete: "完成", failed: "失败", cancelled: "已取消",
};

export function isIdentityJobActive(job: Pick<IdentityJob, "state"> | null): boolean {
  return !!job && (job.state === "queued" || job.state === "preparing" || job.state === "sampling");
}

export type IdentityProfile = {
  id: string;
  referenceKind?: ReferenceKind;
  name: string;
  referenceId: string;
  faceIndex: number;
  state: "preparing" | "ready" | "failed" | "archived";
  featureKey?: string;
  defaults: Partial<Omit<IdentityRequest, "referenceId" | "faceIndex">>;
  error: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AnimeProfile = {
  id: string; name: string; profileId: string; referenceId: string; faceIndex: number;
  sourceJobId: string | null; state: "preparing" | "ready" | "failed"; imageUrl: string; error: string | null;
  sourceKind?: "local-job" | "upload"; sourceName?: string | null; sourceLabel?: string | null;
  sourceImageSha256?: string | null;
};

export type AnimeProfileImport = {
  name: string; profileId: string; sourceName: string; sourceLabel: string; imageBase64: string;
};

export type IdentityBatchRequest = {
  profileId?: string;
  request: IdentityRequest;
  count: number;
  stepValues?: number[];
  previewEvery: 0 | 5 | 10;
};

export type IdentityBatch = {
  id: string;
  parentBatchId?: string;
  originalItemIndices?: number[];
  state: IdentityJob["state"];
  request: IdentityBatchRequest;
  items: IdentityJob[];
  currentItem: number;
  totalItems: number;
  completedItems: number;
  step: number;
  totalSteps: number;
  progress: number;
  stage: string;
  elapsedMs: number;
  etaMs: number | null;
  previewUrl: string | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
};

export const identityDefaults: Omit<IdentityRequest, "referenceId" | "faceIndex"> = {
  modelId: IDENTITY_MODEL_ID,
  prompt: "", negativePrompt: "", seed: "random", width: 512, height: 768, steps: 28, cfg: 5.5,
  identityStrength: 0.82, structureStrength: 0.9, faceLoraStrength: 0.55, loraId: "", loraStrength: 0.6,
  facePolish: false, faceRestoreStrength: 1,
};

export function identityModelDefaults(modelId = IDENTITY_MODEL_ID): typeof identityDefaults {
  const defaults = { ...identityDefaults, modelId };
  if (identityReferenceKind(modelId) === "visual") return {
    ...defaults, width: 768, height: 768, steps: 30, cfg: 5, identityStrength: .8,
    structureStrength: 0, faceLoraStrength: 0, facePolish: false, animeProfileId: null, animeDenoiseStrength: .35, loraId: "",
    visualPolishPrompt: "", visualPolishNegativePrompt: "",
    referenceStart: 0, referenceEnd: 1,
  };
  return modelId === ILLUSTRIOUS_IDENTITY_MODEL_ID ? { ...defaults, width: 768, height: 768, steps: 30, cfg: 5 } : defaults;
}

// Apply on drafts, profile defaults and history replay, not just the model switch UI.
export function normalizeIdentityOptions<T extends Partial<Omit<IdentityRequest, "seed">>>(value: T): T {
  if (identityReferenceKind(value.modelId) !== "visual") return value;
  return { ...value, structureStrength: 0, faceLoraStrength: 0, loraId: "", facePolish: value.facePolish === true,
    animeProfileId: null, animeDenoiseStrength: value.animeDenoiseStrength ?? .35,
    referenceStart: value.referenceStart ?? 0, referenceEnd: value.referenceEnd ?? 1,
    traceLevel: value.traceLevel ?? "off", researchCoverage: "representative" };
}

export function validFaceRestoreStrength(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

// Old profiles, drafts and history may predate these fields. Only explicit true opts in.
export function validAnimeStrength(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= .15 && value <= .65;
}
export function identityFacePolishOptions(value: { modelId?: unknown; facePolish?: unknown; faceRestoreStrength?: unknown; animeProfileId?: unknown; animeDenoiseStrength?: unknown; visualPolishPrompt?: unknown; visualPolishNegativePrompt?: unknown }): Pick<IdentityRequest, "facePolish" | "faceRestoreStrength" | "animeProfileId" | "animeDenoiseStrength" | "visualPolishPrompt" | "visualPolishNegativePrompt"> {
  return { facePolish: value.facePolish === true, faceRestoreStrength: validFaceRestoreStrength(value.faceRestoreStrength) ? value.faceRestoreStrength : 1,
    ...(typeof value.modelId === "string" && identityReferenceKind(value.modelId) === "visual" ? {
      animeProfileId: null, animeDenoiseStrength: validAnimeStrength(value.animeDenoiseStrength) ? value.animeDenoiseStrength : .35,
      visualPolishPrompt: typeof value.visualPolishPrompt === "string" ? value.visualPolishPrompt : "",
      visualPolishNegativePrompt: typeof value.visualPolishNegativePrompt === "string" ? value.visualPolishNegativePrompt : "",
    } : typeof value.animeProfileId === "string" && /^anime-[a-f0-9]{24}$/.test(value.animeProfileId) ? {
      animeProfileId: value.animeProfileId, animeDenoiseStrength: validAnimeStrength(value.animeDenoiseStrength) ? value.animeDenoiseStrength : .35,
    } : {}) };
}

export function identityProfileRequest(profile: IdentityProfile): IdentityRequest {
  // Only generation parameters are eligible defaults, never feature keys or batch controls.
  const visual = profile.referenceKind === "visual" || identityReferenceKind(profile.defaults.modelId) === "visual";
  const visualModel = identityReferenceKind(profile.defaults.modelId) === "visual" ? profile.defaults.modelId! : VISUAL_REFERENCE_MODEL_ID;
  const defaults = visual ? identityModelDefaults(visualModel) : identityDefaults;
  const parameters = Object.fromEntries(Object.entries(defaults).map(([key, fallback]) =>
    [key, profile.defaults[key as keyof typeof identityDefaults] ?? fallback])) as typeof identityDefaults;
  return normalizeIdentityOptions({ ...parameters, ...identityFacePolishOptions({ ...profile.defaults, modelId: visual ? visualModel : parameters.modelId }),
    ...(visual ? { modelId: visualModel } : {}),
    ...(profile.defaults.traceLevel ? { traceLevel: profile.defaults.traceLevel } : {}),
    ...(profile.defaults.researchCoverage ? { researchCoverage: profile.defaults.researchCoverage } : {}),
    referenceId: profile.referenceId, faceIndex: profile.faceIndex });
}

// Completion is a server observation. Invalid receipts must not become success badges.
export function validVisualPolishResult(value: unknown, request: IdentityRequest, expectedJobId: string): value is IdentityFacePolishResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (typeof record.enabled !== "boolean" || typeof record.status !== "string" || !["disabled", "completed", "failed"].includes(record.status)) return false;
  if (record.originalImageUrl != null && (typeof record.originalImageUrl !== "string" || !record.originalImageUrl)) return false;
  if (record.message != null && typeof record.message !== "string") return false;
  if (record.status === "disabled") return record.enabled === false;
  if (record.status === "failed") return record.enabled === true && (record.method == null || record.method === "visual-reference-local-redraw");
  const box = (value: unknown, integer = false): value is number[] => Array.isArray(value) && value.length === 4
    && value.every(n => typeof n === "number" && Number.isFinite(n) && n >= 0 && (!integer || Number.isInteger(n)))
    && value[2] > value[0] && value[3] > value[1];
  const detailFields = ["detailerVersion", "processingSize", "detailPrompt", "detailNegativePrompt"];
  if (detailFields.some(key => key in record)) {
    if (record.detailerVersion !== "masked-face-v1" || !box(record.faceBox) || !box(record.cropBox, true)
      || !Array.isArray(record.processingSize) || record.processingSize.length !== 2) return false;
    const face = record.faceBox, crop = record.cropBox;
    const width = crop[2] - crop[0], height = crop[3] - crop[1];
    const scale = Math.min(Math.max(1, 512 / Math.min(face[2] - face[0], face[3] - face[1])), 768 / Math.max(width, height));
    const size = [Math.floor(width * scale / 8) * 8, Math.floor(height * scale / 8) * 8];
    if (!record.processingSize.every((n, i) => Number.isInteger(n) && n >= 128 && n <= 768 && n === size[i])) return false;
    const detailPrompt = request.visualPolishPrompt?.trim() || "anime face, clean lineart, detailed eyes, natural facial proportions, coherent shading";
    const detailNegative = request.visualPolishNegativePrompt?.trim() || "photograph, photorealistic, blurry, deformed eyes, distorted face, extra eyes, text, watermark";
    if (record.detailPrompt !== detailPrompt || record.detailNegativePrompt !== detailNegative) return false;
  }
  return request.facePolish === true && record.enabled === true && record.method === "visual-reference-local-redraw"
    && typeof record.originalImageUrl === "string" && /^\/api\/identity\/jobs\/identity-[a-f0-9]{24}\/original$/.test(record.originalImageUrl)
    && record.originalImageUrl === `/api/identity/jobs/${expectedJobId}/original`
    && record.referenceId === request.referenceId && record.faceIndex === request.faceIndex
    && typeof record.featureKey === "string" && /^[a-f0-9]{64}$/.test(record.featureKey)
    && box(record.faceBox) && box(record.cropBox, true)
    && validAnimeStrength(record.denoiseStrength) && record.denoiseStrength === (request.animeDenoiseStrength ?? .35)
    && record.outsideMaskUnchanged === true && typeof record.restoreModel === "string" && !!record.restoreModel.trim();
}

export function identityJobSeed(job: IdentityJob): number | "random" {
  const seed = job.result?.metadata.seed;
  return typeof seed === "number" && Number.isSafeInteger(seed) && seed >= 0 ? seed : job.request.seed;
}
