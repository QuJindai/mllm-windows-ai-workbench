import { MockDreamProvider } from "../providers/MockDreamProvider";
import type { GenerationRequest } from "./generation";

const request: GenerationRequest = {
  prompt: "a quiet mountain lake at sunrise",
  negativePrompt: "blurry, low quality",
  modelId: "cyberrealistic-v10-dmd2",
  width: 832,
  height: 1216,
  steps: 8,
  cfg: 1.2,
  seed: 20260906,
  fusionMode: "off",
  traceLevel: "basic",
};

describe("typed Dream provider contract", () => {
  it("returns the local hardware and verified E-drive model fixture", async () => {
    const provider = new MockDreamProvider();
    const hardware = await provider.getHardware();
    const models = await provider.listModels();
    const history = await provider.listHistory({ page: 1, pageSize: 12 });

    expect(hardware.gpuName).toContain("RTX 1000 Ada");
    expect(hardware.vramTotalMiB).toBe(6141);
    expect(hardware.ramTotalBytes).toBeGreaterThan(60_000_000_000);
    expect(models[0]).toMatchObject({
      id: "cyberrealistic-v10-dmd2",
      architecture: "SDXL",
      verified: true,
    });
    expect(models[0].path.toLowerCase()).toContain("e:\\dream");
    expect(history.items.length).toBeGreaterThan(2);
    expect(history.items[1].id).not.toBe(history.items[0].id);
  });

  it("reports generation phases over time instead of injecting a result immediately", async () => {
    const provider = new MockDreamProvider();
    const handle = await provider.generate(request);
    const first = await provider.getJob(handle.id);

    expect(first.state).toBe("queued");
    await new Promise((resolve) => setTimeout(resolve, 160));
    const middle = await provider.getJob(handle.id);
    expect(["preparing", "sampling"]).toContain(middle.state);
    await new Promise((resolve) => setTimeout(resolve, 500));
    const complete = await provider.getJob(handle.id);
    expect(complete.state).toBe("complete");
    expect(complete.result?.truth).toBe("demo");
  });
});
