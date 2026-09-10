import { describe, expect, it } from "vitest";
import { generationStatusLabel, isGenerationTerminal } from "./generate-state";

describe("generation state presentation", () => {
  it("keeps every provider state human-readable", () => {
    expect(generationStatusLabel("queued")).toBe("排队中");
    expect(generationStatusLabel("sampling")).toBe("采样中");
    expect(generationStatusLabel("complete")).toBe("完成");
    expect(generationStatusLabel("unavailable" as never)).toBe("不可用");
  });

  it("only stops polling at terminal states", () => {
    expect(isGenerationTerminal("sampling")).toBe(false);
    expect(isGenerationTerminal("complete")).toBe(true);
    expect(isGenerationTerminal("failed")).toBe(true);
    expect(isGenerationTerminal("cancelled")).toBe(true);
  });
});
