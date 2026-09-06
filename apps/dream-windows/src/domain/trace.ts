import type { TruthLevel } from "./hardware";

export type RuntimeNode = {
  id: string;
  name: string;
  backend: string;
  shape?: string;
  expectedCalls?: number;
  observedCalls?: number;
  durationMs?: number;
  status: "executed" | "running" | "skipped" | "error";
  truth: TruthLevel;
};

export type RuntimeTrace = {
  runId: string;
  totalTimeMs: number;
  nodes: RuntimeNode[];
};

export type ResearchStatus = {
  available: boolean;
  message: string;
  truth: TruthLevel;
};
