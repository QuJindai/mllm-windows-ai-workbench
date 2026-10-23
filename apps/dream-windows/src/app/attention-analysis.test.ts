import { describe, expect, it } from "vitest";
import { aggregateAttentionPeak, fullRegion, regionStatistics } from "./attention-analysis";
import type { RuntimeAttentionMap, RuntimeAttentionMapDescriptor } from "../domain/trace";

describe("attention region and aggregation", () => {
  const map = { width: 2, height: 2, values: [0, .2, .6, 1] } as RuntimeAttentionMap;
  it("computes a region from raw values instead of normalized colors", () => {
    expect(regionStatistics(map, fullRegion)).toEqual({ mean: .45, peak: 1, count: 4 });
    expect(regionStatistics(map, { x: 0, y: .5, width: 1, height: .5 })).toEqual({ mean: .8, peak: 1, count: 2 });
    expect(regionStatistics(map, { x: .9, y: .9, width: 1, height: 1 })).toEqual({ mean: 1, peak: 1, count: 1 });
  });
  it("leaves unsampled combinations missing and averages only matching layers", () => {
    const maps = [{ tokenSlot: 1, step: 0, layerId: "down", peak: .2 }, { tokenSlot: 1, step: 0, layerId: "mid", peak: .8 }, { tokenSlot: 2, step: 0, layerId: "down", peak: 1 }] as RuntimeAttentionMapDescriptor[];
    expect(aggregateAttentionPeak(maps, 1, 0)).toBe(.5);
    expect(aggregateAttentionPeak(maps, 1, 0, "down")).toBe(.2);
    expect(aggregateAttentionPeak(maps, 1, 1)).toBeNull();
  });
});
