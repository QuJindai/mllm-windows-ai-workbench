import { afterEach, expect, it, vi } from "vitest";
import { identityApi } from "./identity-api";

afterEach(() => vi.unstubAllGlobals());

it.each([null, {}, { deleted: "wrong", deletedJobIds: ["job-a"] }, { deleted: "batch-a", deletedJobIds: [] },
  { deleted: "batch-a", deletedJobIds: ["job-a", "job-a"] }, { deleted: "batch-a", deletedJobIds: ["batch-a"] },
  { deleted: "batch-a", deletedJobIds: [null] }])("rejects an incomplete batch receipt: %j", async response => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(response), { status: 200 })));
  await expect(identityApi.deleteBatch("batch-a")).rejects.toThrow();
});
