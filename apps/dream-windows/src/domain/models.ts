export type ModelArchitecture = "SDXL" | "SD15" | "OTHER";
export type ModelFormat = "GGUF" | "SAFETENSORS";

export type ModelRecord = {
  id: string;
  displayName: string;
  architecture: ModelArchitecture;
  format: ModelFormat;
  dmd2: boolean;
  path: string;
  sha256?: string;
  verified: boolean;
  sizeBytes: number;
  tags: string[];
  description: string;
  kind: "Checkpoint" | "LoRA" | "VAE" | "Embedding";
  status: "ready" | "loading" | "error" | "unavailable";
  error?: string;
  imageUrl: string;
};
