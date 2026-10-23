export const MIN_GENERATION_DIMENSION = 512;
export const MIN_GENERATION_STEPS = 8;
export const RECOMMENDED_GENERATION_STEPS = 20;

type GenerationQualityInput = {
  width: number;
  height: number;
  steps: number;
};

type GenerationQualityProfile = {
  minimumSteps?: number;
  recommendedSteps?: number;
  profileLabel?: string;
};

export function generationQualityWarning(
  { width, height, steps }: GenerationQualityInput,
  profile: GenerationQualityProfile = {},
): string | null {
  const minimumSteps = profile.minimumSteps ?? MIN_GENERATION_STEPS;
  const recommendedSteps = profile.recommendedSteps ?? RECOMMENDED_GENERATION_STEPS;
  const profileLabel = profile.profileLabel ?? "当前模型按标准 SDXL 采样";
  const issues: string[] = [];
  if (width < MIN_GENERATION_DIMENSION || height < MIN_GENERATION_DIMENSION) {
    issues.push(`分辨率低于 ${MIN_GENERATION_DIMENSION}×${MIN_GENERATION_DIMENSION}`);
  }
  if (steps < minimumSteps) {
    issues.push(`步数低于 ${minimumSteps}`);
  }
  if (issues.length === 0) return null;
  return `质量保护：${issues.join("，")}，容易出现模糊或结构不完整。${profileLabel}，建议使用至少 ${MIN_GENERATION_DIMENSION}×${MIN_GENERATION_DIMENSION}、${recommendedSteps} 步。`;
}
