import type { TruthLevel } from "./hardware";

export type HistoryItem = {
  id: string;
  title: string;
  prompt: string;
  negativePrompt: string;
  modelId: string;
  modelName: string;
  width: number;
  height: number;
  steps: number;
  cfg: number;
  seed: number;
  generationTimeMs: number;
  createdAt: string;
  imageUrl: string;
  filePath: string;
  tags: string[];
  favorite: boolean;
  status: "complete" | "failed";
  truth: TruthLevel;
};

export type HistoryQuery = {
  page: number;
  pageSize: number;
  search?: string;
  filter?: "all" | "today" | "favorites" | "failed" | "tagged";
};

export type HistoryPage = {
  items: HistoryItem[];
  total: number;
  page: number;
  pageSize: number;
};
