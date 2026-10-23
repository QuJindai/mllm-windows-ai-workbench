import { describe, it, expect } from "vitest";
import { isInfluenceArtifact, isSelfAttentionIndexArtifact } from "./research-artifacts";
import { influenceArtifact, selfIndexArtifact } from "../test/research-artifacts";

describe("identity microscope provenance", () => {
  it("accepts visual reference ablation only with the measured diffusers source", () => {
    const value = { ...influenceArtifact, source: "diffusers-unet", method: "visual-reference-ablation-guided", totalChunks: 1, capturedChunks: 1,
      steps: influenceArtifact.steps.map(step => ({ ...step, chunks: step.chunks.slice(0, 1) })) };
    expect(isInfluenceArtifact(value, value.runId)).toBe(true);
    expect(isInfluenceArtifact({ ...value, source: "debug-unet" }, value.runId)).toBe(false);
  });
  it("accepts measured identity ablation and does not enforce single-text-chunk zero delta", () => {
    const value = { ...influenceArtifact, source:"diffusers-unet", method:"identity-ablation-guided", totalChunks:1, capturedChunks:1,
      steps: influenceArtifact.steps.map(step => ({ ...step, chunks: step.chunks.slice(0,1) })) };
    expect(isInfluenceArtifact(value, value.runId)).toBe(true);
    expect(isInfluenceArtifact({ ...value, source:"debug-unet" }, value.runId)).toBe(false);
  });
  it("accepts bounded extended layers without permitting unknown sources", () => {
    const value = { ...selfIndexArtifact, source:"diffusers-unet",
      layers: [...selfIndexArtifact.layers, ...Array.from({length:4}, (_,i) => ({id:`extra-${i}`,stage:"down",label:`Down ${i}`}))] };
    expect(isSelfAttentionIndexArtifact(value, value.runId)).toBe(true);
    expect(isSelfAttentionIndexArtifact({ ...value, source:"unknown" }, value.runId)).toBe(false);
  });
});
