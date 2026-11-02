// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defaultHQParameters, hqExecutionBasis, validHQParameters } from "../domain/hq-tryon";
import type { HQJob } from "../domain/hq-tryon";
import { hqApi, hqJobFingerprint, readHQDraft, readHQOperations, reconcileHQOperations, reserveHQOperation, saveHQOperation, writeHQDraft } from "./hq-tryon-api";

const bytes = Uint8Array.from("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c49444154789c63606060000000040001f61738550000000049454e44ae426082".match(/../g)!, value => parseInt(value, 16));
const sha = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), n => n.toString(16).padStart(2, "0")).join("");
const body = { personId: "a".repeat(64), garmentId: "SPR-0087", poseId: "P001", parameters: defaultHQParameters };
const job: HQJob = { id: "hq-" + "d".repeat(64), state: "succeeded", pipeline: hqExecutionBasis, identityJobId: "identity-hq-test", inputs: [], result: { sha256: sha } };
class MemoryStorage {
  values: Record<string, string> = {};
  getItem(key: string) { return this.values[key] ?? null; }
  setItem(key: string, value: string) { this.values[key] = value; }
}
beforeEach(() => { vi.stubGlobal("sessionStorage", new MemoryStorage()); vi.stubGlobal("localStorage", new MemoryStorage()); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("local HQ API boundary", () => {
  it("uses local paths, same-origin authentication and exactly the three input IDs without cloud grants", async () => {
    const fetch = vi.fn(async () => Response.json(job)); vi.stubGlobal("fetch", fetch);
    await hqApi.create({ ...body, idempotencyKey: "hq-local-example" });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/hq/jobs"); expect(init.credentials).toBe("same-origin"); expect(init.redirect).toBe("error"); expect(init.method).toBe("POST");
    expect(init.headers).not.toHaveProperty("Authorization"); expect(JSON.parse(String(init.body))).toEqual({ ...body, idempotencyKey: "hq-local-example" });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(hqApi.assetUrl("person", body.personId)).toBe(`/api/hq/asset?kind=person&id=${body.personId}`);
    expect(hqApi.assetUrl("garment", body.garmentId, true)).toBe("/api/hq/asset?kind=garment&id=SPR-0087&thumbnail=1");
    expect(hqApi.inputUrl(job.id, "pose")).toBe(`/api/hq/jobs/${job.id}/inputs/pose`);
    expect(() => hqApi.resultUrl("../outside")).toThrow("编号无效");
  });

  it("reads catalog query pagination and sanitized job list, and rejects malformed job states", async () => {
    const fetch = vi.fn().mockResolvedValueOnce(Response.json({ items: [], total: 0, hasMore: false, categories: ["春"] }))
      .mockResolvedValueOnce(Response.json({ jobs: [job] })).mockResolvedValueOnce(Response.json({ ...job, state: "tool_ready" })); vi.stubGlobal("fetch", fetch);
    await hqApi.catalog("garment", "裙", "春", 2);
    const url = new URL(fetch.mock.calls[0][0], "http://localhost");
    expect(Object.fromEntries(url.searchParams)).toEqual({ kind: "garment", q: "裙", category: "春", page: "2", limit: "24" });
    expect((await hqApi.jobs())[0].id).toBe(job.id); await expect(hqApi.job(job.id)).rejects.toThrow("状态无效");
  });

  it("reports structured authorization errors and never retries a create automatically", async () => {
    const fetch = vi.fn(async () => Response.json({ error: { code: "HQ_AUTH_EXPIRED", message: "请在本机重新授权" } }, { status: 401 })); vi.stubGlobal("fetch", fetch);
    await expect(hqApi.create({ ...body, idempotencyKey: "hq-local-example" })).rejects.toThrow("HQ_AUTH_EXPIRED · 请在本机重新授权"); expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("checks the actual PNG bytes against the job SHA before returning a private blob", async () => {
    const fetch = vi.fn(async () => new Response(bytes, { headers: { "content-type": "image/png", "x-content-sha256": sha } })); vi.stubGlobal("fetch", fetch);
    const blob = await hqApi.result(job);
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(bytes);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`/api/hq/jobs/${job.id}/result`); expect(init.credentials).toBe("same-origin"); expect(init.headers).toBeUndefined();
  });

  it.each(["wrong-bytes", "wrong-header", "wrong-mime", "expired", "missing-job-sha"])("blocks unverified result: %s", async failure => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(failure === "wrong-bytes" ? new TextEncoder().encode("corrupt") : bytes, {
      status: failure === "expired" ? 401 : 200,
      headers: { "content-type": failure === "wrong-mime" ? "text/html" : "image/png", "x-content-sha256": failure === "wrong-header" ? "0".repeat(64) : sha },
    })));
    await expect(hqApi.result(failure === "missing-job-sha" ? { ...job, result: null } : job)).rejects.toThrow();
  });

  it("keeps a stable receipt per fingerprint, whitelists stored fields and fails closed without storage", () => {
    const first = reserveHQOperation(body, []); expect(reserveHQOperation(body, []).idempotencyKey).toBe(first.idempotencyKey);
    const changed = reserveHQOperation({ ...body, parameters: { ...body.parameters, seed: 1 } }, []); expect(changed.idempotencyKey).not.toBe(first.idempotencyKey);
    saveHQOperation({ ...first, jobId: job.id, delivery: "submitted", ignoredSecret: "must-not-persist" } as typeof first);
    expect(readHQOperations().find(item => item.fingerprint === first.fingerprint)?.jobId).toBe(job.id);
    writeHQDraft({ selection: { person: { id: body.personId, label: "人物", unsafeToken: "must-not-persist" } as never }, parameters: defaultHQParameters, activeJobId: job.id });
    expect(readHQDraft()?.selection.person?.id).toBe(body.personId);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("must-not-persist");
    expect(JSON.stringify({ ...localStorage })).not.toContain("must-not-persist");
    vi.spyOn(MemoryStorage.prototype, "setItem").mockImplementation(() => { throw new Error("storage unavailable"); });
    expect(() => reserveHQOperation({ ...body, poseId: "P002" }, [])).toThrow("storage unavailable");
  });

  it("retains an uncertain request key after the entire tab session is discarded", () => {
    const first = reserveHQOperation(body, []);
    saveHQOperation({ ...first, delivery: "unknown" });
    vi.stubGlobal("sessionStorage", new MemoryStorage());
    const restored = reserveHQOperation(body, []);
    expect(restored.idempotencyKey).toBe(first.idempotencyKey); expect(restored.delivery).toBe("unknown");
  });

  it.each([[7, "local"], [7, "session"], [10, "local"], [10, "session"]] as const)("never promotes an unqualified %i-field %s receipt into the current execution basis", (length, storage) => {
    const fields = [body.personId, body.garmentId, body.poseId, 0, 512, 768, 24];
    const fingerprint = JSON.stringify(length === 7 ? fields : [...fields, null, false, .35]);
    const legacy = JSON.stringify([{ fingerprint, idempotencyKey: "hq-local-legacy-request", jobId: "hq-old", delivery: "submitted", secret: "never-copy" }]);
    const oldStorage = storage === "local" ? localStorage : sessionStorage;
    oldStorage.setItem("dream.hq.operations.v1", legacy);
    const current = reserveHQOperation(body, []);
    expect(current.idempotencyKey).not.toBe("hq-local-legacy-request"); expect(current.jobId).toBeUndefined();
    expect(JSON.parse(current.fingerprint)[0]).toBe(hqExecutionBasis);
    expect(current.idempotencyKey).toContain(hqExecutionBasis);
    expect(oldStorage.getItem("dream.hq.operations.v1")).toBe(legacy);
    expect(localStorage.getItem("dream.hq.operations.v2")).not.toContain("never-copy");
    vi.stubGlobal("sessionStorage", new MemoryStorage());
    expect(reserveHQOperation(body, []).idempotencyKey).toBe(current.idempotencyKey);
  });

  it.each([
    { pipeline: "hq-three-image-sd15-v1", identityJobId: "identity-old" },
    { pipeline: hqExecutionBasis, identityJobId: null },
    { pipeline: undefined, identityJobId: "identity-unqualified" },
  ])("does not reconcile or block the current basis with a legacy server record: %j", legacyFields => {
    const legacy: HQJob = { ...job, ...legacyFields, requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId },
      parameters: body.parameters, idempotencyKey: "hq-local-legacy-request" };
    expect(hqJobFingerprint(legacy)).toBeNull();
    const fresh = reserveHQOperation(body, [legacy]);
    expect(fresh.jobId).toBeUndefined(); expect(fresh.idempotencyKey).not.toBe(legacy.idempotencyKey);
    // Missing inputs in an old downloading record must not lock a new-basis request.
    localStorage.setItem("dream.hq.operations.v2", "[]");
    expect(reserveHQOperation(body, [{ ...legacy, state: "queued", phase: "downloading", parameters: undefined, requestedInputIds: undefined }]).jobId).toBeUndefined();
  });

  it("never attaches a legacy server job through the matching-key fallback", () => {
    const current = reserveHQOperation(body, []); saveHQOperation({ ...current, delivery: "unknown" });
    const legacy: HQJob = { ...job, pipeline: "hq-three-image-sd15-v1", identityJobId: null, idempotencyKey: current.idempotencyKey };
    const [restored] = reconcileHQOperations([legacy]);
    expect(restored).toMatchObject({ idempotencyKey: current.idempotencyKey, delivery: "unknown" });
    expect(restored.jobId).toBeUndefined();
  });

  it("recovers a mature historical job only from an explicit matching audit basis and rejects conflicting pipeline evidence", () => {
    const mature: HQJob = { ...job, pipeline: undefined, audit: { pipeline: hqExecutionBasis },
      requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId }, parameters: body.parameters, idempotencyKey: "hq-existing-mature-request" };
    expect(reserveHQOperation(body, [mature])).toMatchObject({ jobId: job.id, idempotencyKey: mature.idempotencyKey });
    expect(hqJobFingerprint({ ...mature, pipeline: "hq-three-image-sd15-v1" })).toBeNull();
  });

  it("refuses a new key when an unrecognized downloading task cannot yet be compared", () => {
    const downloading: HQJob = { ...job, state: "queued", phase: "downloading", inputs: [], idempotencyKey: "hq-existing-unknown-inputs" };
    expect(() => reserveHQOperation(body, [downloading])).toThrow("尚未返回完整三图编号");
    expect(readHQOperations()).toHaveLength(0);
  });

  it("recovers the initial downloading receipt by requested IDs and explicit identity options before pixels exist", () => {
    const request = { ...body, profileId: "person-existing", facePolish: true, faceRestoreStrength: .35 };
    const downloading: HQJob = { ...job, state: "queued", phase: "downloading", inputs: [], result: null,
      requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId }, parameters: body.parameters,
      profileId: request.profileId, facePolish: true, faceRestoreStrength: .35, idempotencyKey: "hq-existing-profile-request" };
    const restored = reserveHQOperation(request, [downloading]);
    expect(restored).toMatchObject({ jobId: job.id, idempotencyKey: downloading.idempotencyKey, delivery: "submitted" });
    vi.stubGlobal("sessionStorage", new MemoryStorage());
    expect(reserveHQOperation(request, []).idempotencyKey).toBe(restored.idempotencyKey);
    const alternatives = [reserveHQOperation({ ...request, profileId: null }, [downloading]),
      reserveHQOperation({ ...request, facePolish: false }, [downloading]),
      reserveHQOperation({ ...request, faceRestoreStrength: .4 }, [downloading])];
    expect(new Set([restored, ...alternatives].map(receipt => receipt.idempotencyKey)).size).toBe(4);
    expect(reserveHQOperation(request, [downloading]).idempotencyKey).toBe(restored.idempotencyKey);
  });

  it.each([{ width: 768, height: 768 }, { steps: 51 }, { width: 1024 }, { seed: -1 }, { seed: 2147483648 }, { height: 257 }])("enforces real local pipeline limits: %j", invalid => {
    expect(validHQParameters({ ...defaultHQParameters, ...invalid })).toBe(false);
    expect(validHQParameters(defaultHQParameters)).toBe(true);
  });
});
