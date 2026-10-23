import type { RuntimeAttentionMap, RuntimeAttentionMapDescriptor } from "../domain/trace";

export type AttentionRegion = { x: number; y: number; width: number; height: number };
export const fullRegion: AttentionRegion = { x: 0, y: 0, width: 1, height: 1 };

export function regionStatistics(map: RuntimeAttentionMap, region: AttentionRegion) {
  const x0 = Math.max(0, Math.min(map.width - 1, Math.floor(region.x * map.width)));
  const y0 = Math.max(0, Math.min(map.height - 1, Math.floor(region.y * map.height)));
  const x1 = Math.max(x0 + 1, Math.min(map.width, Math.ceil((region.x + region.width) * map.width)));
  const y1 = Math.max(y0 + 1, Math.min(map.height, Math.ceil((region.y + region.height) * map.height)));
  let sum = 0, peak = -Infinity, count = 0;
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
    const value = map.values[y * map.width + x];
    if (!Number.isFinite(value)) continue;
    sum += value; peak = Math.max(peak, value); count++;
  }
  return count ? { mean: sum / count, peak, count } : null;
}

export function aggregateAttentionPeak(maps: RuntimeAttentionMapDescriptor[], token: number, step: number, layer?: string): number | null {
  const selected = maps.filter((entry) => entry.tokenSlot === token && entry.step === step && (!layer || entry.layerId === layer));
  return selected.length ? selected.reduce((sum, entry) => sum + entry.peak, 0) / selected.length : null;
}
