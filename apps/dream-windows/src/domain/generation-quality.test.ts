import { describe, expect, it } from "vitest";
import { generationQualityWarning } from "./generation-quality";

describe("generation quality guard", () => {
  it("warns before submitting a low-resolution, low-step SDXL request", () => {
    expect(generationQualityWarning({ width: 256, height: 256, steps: 2 })).toContain("质量保护");
  });

  it("allows the normal SDXL quality profile", () => {
    expect(generationQualityWarning({ width: 832, height: 1216, steps: 20 })).toBeNull();
  });

  it("allows a verified low-step distilled profile at its recommended step count", () => {
    expect(generationQualityWarning(
      { width: 768, height: 768, steps: 4 },
      { minimumSteps: 4, recommendedSteps: 4, profileLabel: "Lightning 蒸馏模型" },
    )).toBeNull();
  });
});
