// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defaultHQParameters, hqExecutionBasis, validHQParameters } from "../domain/hq-tryon";
import type { HQJob } from "../domain/hq-tryon";
import { hqApi, hqJobFingerprint, readHQDraft, readHQOperations, reconcileHQOperations, reserveHQOperation, reserveHQRetry, saveHQOperation, writeHQDraft } from "./hq-tryon-api";

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
  it("advances only an authoritative terminal retry to a uniquely newer job with the same execution basis and settings", () => {
    const b: HQJob = { ...job, id: "hq-b", state: "failed", idempotencyKey: "hq-attempt-b", createdAt: "2026-11-02T03:00:00.123455+00:00", parameters: body.parameters,
      requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId } };
    const c: HQJob = { ...b, id: "hq-c", state: "succeeded", idempotencyKey: "hq-attempt-c", createdAt: "2026-11-02T04:00:00.123456+01:00" };
    const receipt = { fingerprint: hqJobFingerprint(b)!, jobId: b.id, idempotencyKey: b.idempotencyKey!, retryOf: "hq-a", delivery: "submitted" as const };
    const snapshots: HQJob[][] = [
      [c], [{ ...b, state: "running" }, c], [{ ...b, createdAt: undefined }, c], [b, { ...c, createdAt: undefined }],
      [b, { ...c, createdAt: b.createdAt }], [b, { ...c, createdAt: "2026-10-01T00:00:00Z" }], [b, { ...c, createdAt: "2027-02-30T00:00:00Z" }],
      [b, { ...c, pipeline: "old-pipeline" }], [b, { ...c, identityJobId: null }], [b, { ...c, parameters: { ...body.parameters, seed: 1 } }],
      [b, c, { ...c, id: "hq-d", idempotencyKey: "hq-attempt-d" }],
    ];
    for (const jobs of snapshots) {
      vi.stubGlobal("localStorage", new MemoryStorage()); saveHQOperation(receipt);
      expect(reconcileHQOperations(jobs).find(row => row.fingerprint === receipt.fingerprint)).toEqual(receipt);
    }
    for (const delivery of ["prepared", "unknown"] as const) {
      const pending = { ...receipt, jobId: undefined, delivery };
      saveHQOperation(pending);
      expect(reconcileHQOperations([c])[0]).toEqual(pending);
    }
    saveHQOperation(receipt);
    expect(reconcileHQOperations([b, c])[0]).toMatchObject({ jobId: c.id, idempotencyKey: c.idempotencyKey, retryOf: b.id });
    expect(reconcileHQOperations([b])[0].jobId).toBe(c.id);
    expect(() => saveHQOperation(receipt)).toThrow("请求回执已更新");
  });

  it.each(["failed", "cancelled"] as const)("fences an explicit %s retry from old reconciliation and late receipts across sessions", async state => {
    const old: HQJob = { ...job, state, parameters: body.parameters, requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId }, idempotencyKey: "hq-original-failed-attempt" };
    const original = reserveHQOperation(body, [old]);
    const fresh = await reserveHQRetry(body, [old], original.idempotencyKey);
    expect(fresh.idempotencyKey).not.toBe(original.idempotencyKey);
    expect(fresh).toMatchObject({ fingerprint: original.fingerprint, retryOf: old.id, delivery: "prepared" });
    expect(fresh.jobId).toBeUndefined();
    saveHQOperation({ ...fresh, delivery: "unknown" });
    vi.stubGlobal("sessionStorage", new MemoryStorage());
    expect(reserveHQOperation(body, [old])).toMatchObject({ idempotencyKey: fresh.idempotencyKey, delivery: "unknown" });
    expect(() => saveHQOperation(original)).toThrow("请求回执已更新");
    await expect(reserveHQRetry(body, [old], original.idempotencyKey)).rejects.toThrow("请求回执已更新");
    const created: HQJob = { ...old, id: "hq-explicit-retry", state: "queued", idempotencyKey: fresh.idempotencyKey };
    expect(reconcileHQOperations([old, created])[0]).toMatchObject({ idempotencyKey: fresh.idempotencyKey, jobId: created.id, delivery: "submitted" });
    expect(reconcileHQOperations([old])[0].jobId).toBe(created.id);
    expect(old.state).toBe(state);
    // An independent browser looking at the same terminal also submits the same successor key.
    vi.stubGlobal("localStorage", new MemoryStorage());
    expect((await reserveHQRetry(body, [old], original.idempotencyKey)).idempotencyKey).toBe(fresh.idempotencyKey);
    const nextFailed = { ...created, state: "failed" as const };
    expect((await reserveHQRetry(body, [old, nextFailed], fresh.idempotencyKey)).idempotencyKey).not.toBe(fresh.idempotencyKey);
  });

  it.each(["queued", "running", "succeeded"] as const)("cannot allocate an explicit retry for a %s job", async state => {
    const current: HQJob = { ...job, state, cancellationRequested: state === "running", parameters: body.parameters,
      requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId }, idempotencyKey: "hq-original-live-attempt" };
    const receipt = reserveHQOperation(body, [current]);
    const digest = vi.spyOn(crypto.subtle, "digest");
    await expect(reserveHQRetry(body, [current], receipt.idempotencyKey)).rejects.toThrow("失败或已取消");
    expect(digest).not.toHaveBeenCalled();
    expect(readHQOperations()).toEqual([receipt]);
  });

  it("requires matching settings and refuses retry when another matching attempt is still active", async () => {
    const old: HQJob = { ...job, state: "failed", parameters: body.parameters,
      requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId }, idempotencyKey: "hq-original-failed-attempt" };
    const receipt = reserveHQOperation(body, [old]);
    await expect(reserveHQRetry({ ...body, parameters: { ...body.parameters, seed: 1 } }, [old], receipt.idempotencyKey)).rejects.toThrow();
    await expect(reserveHQRetry(body, [old, { ...old, id: "hq-another-active", state: "running", idempotencyKey: "hq-another-active-key" }], receipt.idempotencyKey)).rejects.toThrow("失败或已取消");
    expect(readHQOperations()).toEqual([receipt]);
  });

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

  it("still reconciles an ordinary unsent reservation with a matching server job discovered on refresh", () => {
    const unsent = reserveHQOperation(body, []);
    const existing: HQJob = { ...job, state: "running", parameters: body.parameters, requestedInputIds: { person: body.personId, garment: body.garmentId, pose: body.poseId },
      idempotencyKey: "hq-existing-active-attempt" };
    expect(unsent.idempotencyKey).not.toBe(existing.idempotencyKey);
    expect(reserveHQOperation(body, [existing])).toMatchObject({ jobId: existing.id, idempotencyKey: existing.idempotencyKey, delivery: "submitted" });
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

  it.each([[512, 768], [640, 960], [768, 1152], [768, 512], [960, 640], [1152, 768]])("accepts native preset %s x %s while retaining the standard default", (width, height) => {
    expect(validHQParameters({ ...defaultHQParameters, width, height })).toBe(true);
    expect(defaultHQParameters).toMatchObject({ width: 512, height: 768 });
    const request = { ...body, parameters: { ...defaultHQParameters, width, height } };
    const receipt = reserveHQOperation(request, []);
    expect(reserveHQOperation(request, []).idempotencyKey).toBe(receipt.idempotencyKey);
  });

  it.each([{ width: 1152, height: 832 }, { steps: 51 }, { width: 1216 }, { seed: -1 }, { seed: 2147483648 }, { height: 257 }])("enforces real local pipeline limits: %j", invalid => {
    expect(validHQParameters({ ...defaultHQParameters, ...invalid })).toBe(false);
    expect(validHQParameters(defaultHQParameters)).toBe(true);
  });
});
