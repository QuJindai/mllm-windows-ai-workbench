export type DreamSettings = {
  dreamRoot: string;
  modelsPath: string;
  outputsPath: string;
  historyPath: string;
  cachePath: string;
  logsPath: string;
  autopilotEnabled: boolean;
  precisionMode: "fp16" | "fp32";
  fallbackToCpu: boolean;
  tileMode: "automatic" | "enabled" | "disabled";
  vaeMemoryMode: "sliced" | "full";
  attentionSlicing: boolean;
  vramThresholdGb: number;
  optimizationLevel: "conservative" | "balanced" | "aggressive";
};

export type WorkspaceEntry = "base" | "models" | "outputs" | "history" | "cache" | "logs";

export type WorkspaceOpenResult = {
  opened: boolean;
  entry: WorkspaceEntry;
  path: string;
};
