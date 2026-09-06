import type { GenerationState } from "../domain/generation";

const labels: Record<GenerationState | "unavailable", string> = {
  idle: "Idle",
  queued: "Queued",
  preparing: "Preparing",
  sampling: "Sampling",
  decoding: "Decoding",
  saving: "Saving",
  complete: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
  unavailable: "Unavailable",
};

export function generationStatusLabel(state: GenerationState | "unavailable"): string {
  return labels[state];
}

export function isGenerationTerminal(state: GenerationState): boolean {
  return state === "complete" || state === "failed" || state === "cancelled";
}
