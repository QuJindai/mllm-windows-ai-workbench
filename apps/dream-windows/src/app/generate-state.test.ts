import { describe, expect, it } from "vitest";
import { generationStatusLabel, isGenerationTerminal } from "./generate-state";

describe("generation state presentation", () => {
  it("keeps every provider state human-readable", () => {
    expect(generationStatusLabel("queued")).toBe("Queued");
    expect(generationStatusLabel("sampling")).toBe("Sampling");
    expect(generationStatusLabel("complete")).toBe("Complete");
    expect(generationStatusLabel("unavailable" as never)).toBe("Unavailable");
  });

  it("only stops polling at terminal states", () => {
    expect(isGenerationTerminal("sampling")).toBe(false);
    expect(isGenerationTerminal("complete")).toBe(true);
    expect(isGenerationTerminal("failed")).toBe(true);
    expect(isGenerationTerminal("cancelled")).toBe(true);
  });
});
