import type { GenerationState } from "../domain/generation";

const labels: Record<GenerationState | "unavailable", string> = {
  idle: "空闲",
  queued: "排队中",
  preparing: "准备中",
  sampling: "采样中",
  decoding: "解码中",
  saving: "保存中",
  complete: "完成",
  failed: "失败",
  cancelled: "已取消",
  unavailable: "不可用",
};

export function generationStatusLabel(state: GenerationState | "unavailable"): string {
  return labels[state];
}

export function isGenerationTerminal(state: GenerationState): boolean {
  return state === "complete" || state === "failed" || state === "cancelled";
}
