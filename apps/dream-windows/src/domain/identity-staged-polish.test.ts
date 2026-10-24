import { describe, expect, it } from "vitest";
import {
  IDENTITY_MODEL_ID, ILLUSTRIOUS_IDENTITY_MODEL_ID, VISUAL_REFERENCE_MODEL_ID,
  identityFacePolishOptions, identityModelDefaults, identityProfileRequest, normalizeIdentityOptions,
  validVisualPolishResult,
} from "./identity";
import type { IdentityRequest } from "./identity";

const jobId = "identity-0123456789abcdef01234567";
const staged = { visualPolishMode: "reference-anchor" as const, visualAnchorStrength: .8, visualPolishPasses: 2 as const };
const request = { ...identityModelDefaults(VISUAL_REFERENCE_MODEL_ID), ...staged, facePolish: true,
  referenceId: "ref-a", faceIndex: 0, animeDenoiseStrength: .25,
  visualPolishPrompt: "clean eyes", visualPolishNegativePrompt: "blur" } satisfies IdentityRequest;
const harmonize = { kind: "harmonize", denoiseStrength: .25, steps: 7, durationMs: 1234 };
const detail = { kind: "detail", denoiseStrength: .15, steps: 4, durationMs: 678 };
const snapshots = ["anchor", "harmonize", "detail"].map(kind => ({ kind, imageUrl: `/api/identity/jobs/${jobId}/stages/${kind}` }));
const receipt = {
  enabled: true, status: "completed", method: "visual-reference-local-redraw",
  originalImageUrl: `/api/identity/jobs/${jobId}/original`, referenceId: "ref-a", faceIndex: 0,
  featureKey: "a".repeat(64), faceBox: [20, 30, 120, 130], cropBox: [0, 0, 160, 160],
  outsideMaskUnchanged: true, restoreModel: "CyberRealistic XL", denoiseStrength: .25,
  detailerVersion: "staged-face-v2", processingSize: [768, 768], detailPrompt: "clean eyes", detailNegativePrompt: "blur",
  polishMode: "reference-anchor", anchorStrength: .8, alignmentError: .04, passes: [harmonize, detail], snapshots,
};

describe("staged settings across request restoration", () => {
  it("defaults old visual requests to one redraw pass", () => {
    expect(normalizeIdentityOptions({ modelId: VISUAL_REFERENCE_MODEL_ID })).toMatchObject({
      visualPolishMode: "redraw", visualAnchorStrength: .95, visualPolishPasses: 1,
    });
    expect(identityFacePolishOptions({ modelId: VISUAL_REFERENCE_MODEL_ID })).toMatchObject({
      visualPolishMode: "redraw", visualAnchorStrength: .95, visualPolishPasses: 1,
    });
  });

  it("keeps explicit staged profile settings and the adjusted first denoise", () => {
    const restored = identityProfileRequest({ id: "person-a", name: "参考", referenceKind: "visual", referenceId: "ref-a",
      faceIndex: 0, state: "ready", defaults: request, error: null, createdAt: "", updatedAt: "" });
    expect(restored).toMatchObject({ ...staged, animeDenoiseStrength: .25 });
  });

  it.each([IDENTITY_MODEL_ID, ILLUSTRIOUS_IDENTITY_MODEL_ID])("clears staged settings for nonvisual model %s", modelId => {
    expect(normalizeIdentityOptions({ ...request, modelId })).toMatchObject({
      visualPolishMode: "redraw", visualAnchorStrength: .95, visualPolishPasses: 1,
    });
    expect(identityFacePolishOptions({ ...request, modelId })).toMatchObject({
      visualPolishMode: "redraw", visualAnchorStrength: .95, visualPolishPasses: 1,
    });
  });

  it("sanitizes malformed persisted options while retaining a valid first-round strength", () => {
    expect(identityFacePolishOptions({ modelId: VISUAL_REFERENCE_MODEL_ID, visualPolishMode: "other",
      visualAnchorStrength: .29, visualPolishPasses: 3, animeDenoiseStrength: .4 })).toMatchObject({
      visualPolishMode: "redraw", visualAnchorStrength: .95, visualPolishPasses: 1, animeDenoiseStrength: .4,
    });
  });
});

describe("staged completion evidence", () => {
  it.each([1, 2] as const)("accepts protected-face-v3 for %s anchor passes without changing the request", count => {
    const params = { ...request, visualPolishPasses: count };
    const before = structuredClone(params);
    expect(validVisualPolishResult({ ...receipt, detailerVersion: "protected-face-v3", featureProtection: "central-features-v1",
      passes: count === 1 ? [harmonize] : [harmonize, detail], snapshots: count === 1 ? snapshots.slice(0, 2) : snapshots }, params, jobId)).toBe(true);
    expect(params).toEqual(before);
  });

  it.each([undefined, null, "central-features-v2", true])("rejects v3 without its exact feature protection marker: %j", featureProtection => {
    expect(validVisualPolishResult({ ...receipt, detailerVersion: "protected-face-v3", featureProtection }, request, jobId)).toBe(false);
  });

  it("does not allow redraw to claim protected-face-v3", () => {
    const { anchorStrength: _anchor, alignmentError: _error, ...base } = receipt;
    expect(validVisualPolishResult({ ...base, detailerVersion: "protected-face-v3", featureProtection: "central-features-v1",
      polishMode: "redraw", snapshots: snapshots.slice(1) }, { ...request, visualPolishMode: "redraw" }, jobId)).toBe(false);
  });

  it("keeps v2 valid without reclassifying it as protected", () => {
    expect(validVisualPolishResult(receipt, request, jobId)).toBe(true);
    expect(validVisualPolishResult({ ...receipt, featureProtection: "central-features-v1" }, request, jobId)).toBe(false);
    const { polishMode: _mode, anchorStrength: _anchor, alignmentError: _error, passes: _passes, snapshots: _snapshots, ...base } = receipt;
    expect(validVisualPolishResult({ ...base, detailerVersion: "masked-face-v1", featureProtection: "central-features-v1" },
      { ...request, visualPolishMode: "redraw", visualPolishPasses: 1 }, jobId)).toBe(false);
  });

  it.each([undefined, null])("keeps a nullable legacy v2 protection field unclaimed: %j", featureProtection => {
    expect(validVisualPolishResult({ ...receipt, featureProtection }, request, jobId)).toBe(true);
  });

  it.each([
    { snapshots: undefined }, { snapshots: [...snapshots].reverse() },
    { passes: [harmonize, { ...detail, steps: 5 }] }, { alignmentError: .181 },
    { passes: [harmonize] }, { processingSize: [512, 512] },
  ])("applies the existing staged evidence checks to v3: %j", invalid => {
    expect(validVisualPolishResult({ ...receipt, detailerVersion: "protected-face-v3", featureProtection: "central-features-v1", ...invalid },
      request, jobId)).toBe(false);
  });

  it("accepts complete passes bound to requested strengths with their measured timings", () => {
    expect(validVisualPolishResult(receipt, request, jobId)).toBe(true);
    expect(validVisualPolishResult({ ...receipt, passes: [harmonize], snapshots: snapshots.slice(0, 2) }, { ...request, visualPolishPasses: 1 }, jobId)).toBe(true);
    const { anchorStrength: _anchor, alignmentError: _error, ...redraw } = receipt;
    expect(validVisualPolishResult({ ...redraw, polishMode: "redraw", snapshots: snapshots.slice(1) },
      { ...request, visualPolishMode: "redraw" }, jobId)).toBe(true);
  });

  it.each([[.15, 4], [.25, 7], [.35, 10], [.65, 19]])("binds first pass denoise %s to exactly %s steps", (strength, steps) => {
    const params = { ...request, animeDenoiseStrength: strength };
    const result = { ...receipt, denoiseStrength: strength, passes: [{ ...harmonize, denoiseStrength: strength, steps }, detail] };
    expect(validVisualPolishResult(result, params, jobId)).toBe(true);
    expect(validVisualPolishResult({ ...result, passes: [{ ...result.passes[0], steps: steps + 1 }, detail] }, params, jobId)).toBe(false);
  });

  it.each([3, 5, 30])("rejects incorrect second-pass step count %s at fixed .15 denoise", steps => {
    expect(validVisualPolishResult({ ...receipt, passes: [harmonize, { ...detail, steps }] }, request, jobId)).toBe(false);
  });

  it.each([
    { polishMode: "redraw" }, { polishMode: undefined }, { anchorStrength: .95 }, { anchorStrength: .29 },
    { alignmentError: undefined }, { alignmentError: -.01 }, { alignmentError: Infinity }, { alignmentError: "0.04" },
    { alignmentError: .180000001 }, { alignmentError: .181 }, { alignmentError: .5 },
    { passes: undefined }, { passes: [] }, { passes: [harmonize] }, { passes: [detail, harmonize] },
    { passes: [harmonize, { ...detail, kind: "other" }] }, { passes: [harmonize, { ...detail, denoiseStrength: .25 }] },
    { passes: [{ ...harmonize, denoiseStrength: .35 }, detail] }, { passes: [harmonize, { ...detail, steps: 0 }] },
    { passes: [harmonize, { ...detail, steps: 1.5 }] }, { passes: [harmonize, { ...detail, durationMs: -1 }] },
    { passes: [harmonize, { ...detail, durationMs: NaN }] }, { passes: [harmonize, { ...detail, durationMs: "678" }] },
    { detailerVersion: "masked-face-v1" }, { detailerVersion: undefined }, { outsideMaskUnchanged: false },
  ])("rejects incomplete or mismatched staged evidence: %j", invalid => {
    expect(validVisualPolishResult({ ...receipt, ...invalid }, request, jobId)).toBe(false);
  });

  it("keeps legacy redraw receipts valid but never uses them to confirm an anchor or second pass", () => {
    const { polishMode: _mode, anchorStrength: _anchor, alignmentError: _error, passes: _passes, snapshots: _snapshots, ...base } = receipt;
    const legacy = { ...base, detailerVersion: "masked-face-v1" };
    const { visualPolishMode: _requestedMode, visualPolishPasses: _requestedPasses, ...oldRequest } = request;
    expect(validVisualPolishResult(legacy, oldRequest, jobId)).toBe(true);
    expect(validVisualPolishResult(legacy, request, jobId)).toBe(false);
  });

  it("rejects a non-string legacy version instead of coercing JSON into a known version", () => {
    const { polishMode: _mode, anchorStrength: _anchor, alignmentError: _error, passes: _passes, snapshots: _snapshots, ...base } = receipt;
    expect(validVisualPolishResult({ ...base, detailerVersion: ["masked-face-v1"] },
      { ...request, visualPolishMode: "redraw", visualPolishPasses: 1 }, jobId)).toBe(false);
  });

  it.each([0, .18])("accepts alignment error boundary %s", alignmentError => {
    expect(validVisualPolishResult({ ...receipt, alignmentError }, request, jobId)).toBe(true);
  });

  it.each([
    ["reference-anchor", 1, ["anchor", "harmonize"]],
    ["reference-anchor", 2, ["anchor", "harmonize", "detail"]],
    ["redraw", 2, ["harmonize", "detail"]],
  ] as const)("requires exactly the canonical snapshot sequence for %s / %s passes", (mode, count, kinds) => {
    const { anchorStrength: _anchor, alignmentError: _error, ...base } = receipt;
    const result = { ...base, polishMode: mode, passes: count === 1 ? [harmonize] : [harmonize, detail],
      ...(mode === "reference-anchor" ? { anchorStrength: .8, alignmentError: .04 } : {}),
      snapshots: kinds.map(kind => ({ kind, imageUrl: `/api/identity/jobs/${jobId}/stages/${kind}` })) };
    const params = { ...request, visualPolishMode: mode, visualPolishPasses: count };
    expect(validVisualPolishResult(result, params, jobId)).toBe(true);
    const { snapshots: _snapshots, ...missing } = result;
    expect(validVisualPolishResult(missing, params, jobId)).toBe(false);
    expect(validVisualPolishResult({ ...result, snapshots: [] }, params, jobId)).toBe(false);
    expect(validVisualPolishResult({ ...result, snapshots: result.snapshots.slice(1) }, params, jobId)).toBe(false);
    expect(validVisualPolishResult({ ...result, snapshots: [...result.snapshots, result.snapshots[0]] }, params, jobId)).toBe(false);
    if (count === 2 || mode === "reference-anchor") {
      expect(validVisualPolishResult({ ...result, snapshots: [...result.snapshots].reverse() }, params, jobId)).toBe(false);
    }
  });

  it.each([{ anchorStrength: .8 }, { alignmentError: .1 }])("rejects anchor evidence on redraw mode: %j", extra => {
    const { anchorStrength: _anchor, alignmentError: _error, ...base } = receipt;
    expect(validVisualPolishResult({ ...base, polishMode: "redraw", snapshots: snapshots.slice(1), ...extra },
      { ...request, visualPolishMode: "redraw" }, jobId)).toBe(false);
  });

  it.each([
    null, {}, [{ kind: "other", imageUrl: `/api/identity/jobs/${jobId}/stages/other` }, ...snapshots.slice(1)],
    [{ kind: "anchor", imageUrl: "/anchor.png" }, ...snapshots.slice(1)],
    [{ kind: "anchor", imageUrl: `/api/identity/jobs/identity-aaaaaaaaaaaaaaaaaaaaaaaa/stages/anchor` }, ...snapshots.slice(1)],
    [{ kind: "anchor", imageUrl: `https://example.com/api/identity/jobs/${jobId}/stages/anchor` }, ...snapshots.slice(1)],
    [{ kind: "anchor", imageUrl: `/api/identity/jobs/${jobId}/stages/detail` }, ...snapshots.slice(1)],
    [{ kind: "anchor", imageUrl: `/api/identity/jobs/${jobId}/stages/anchor?other=1` }, ...snapshots.slice(1)],
    [snapshots[0], snapshots[0], snapshots[2]],
  ])("rejects malformed, duplicated or foreign snapshots: %j", snapshots => {
    expect(validVisualPolishResult({ ...receipt, snapshots }, request, jobId)).toBe(false);
  });

  it("does not advertise an unrequested detail or anchor stage", () => {
    expect(validVisualPolishResult({ ...receipt, passes: [harmonize], snapshots: [{ kind: "detail", imageUrl: `/api/identity/jobs/${jobId}/stages/detail` }] },
      { ...request, visualPolishPasses: 1 }, jobId)).toBe(false);
    expect(validVisualPolishResult({ ...receipt, polishMode: "redraw", snapshots: [{ kind: "anchor", imageUrl: `/api/identity/jobs/${jobId}/stages/anchor` }] },
      { ...request, visualPolishMode: "redraw" }, jobId)).toBe(false);
  });
});
