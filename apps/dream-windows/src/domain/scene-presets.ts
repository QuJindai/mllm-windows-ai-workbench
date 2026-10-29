import scenes from "./scene-presets.json";
import { identityModelDefaults, isIdentityModelId } from "./identity";

export const scenePresets = scenes;
export type ScenePreset = typeof scenes[number];
export type SceneStyle = "photo" | "anime";
export type SceneFraming = "portrait" | "half" | "full";
export type ScenePrompts = { prompt: string; negativePrompt: string };
export type SceneRecipe = { width: number; height: number; steps: number; cfg: number };
export type SceneFullBodyRecipe = SceneRecipe & { identityStrength: number; referenceStart: number; referenceEnd: number };

export function sceneFullBodyRecipe(modelId: string, style: SceneStyle, framing: SceneFraming): SceneFullBodyRecipe | null {
  if (modelId !== "cyberrealistic-xl-plus-face" || style !== "anime" || framing !== "full") return null;
  return { width: 512, height: 768, steps: 30, cfg: 5, identityStrength: .7, referenceStart: .35, referenceEnd: 1 };
}

// Fallbacks for catalog entries without generationDefaults. Values match the local
// config/dream/model-registry.json and GeneratePage's CyberRealistic defaults.
// Live catalog values take precedence. Identity routes have their own size limits.
const generationRecipes: Record<string, SceneRecipe> = {
  "cyberrealistic-xl-v10-standard": { width: 768, height: 768, steps: 20, cfg: 4 },
  "animagine-xl-4.0-opt-standard": { width: 768, height: 768, steps: 28, cfg: 5 },
  "dreamshaper-xl-lightning": { width: 768, height: 768, steps: 8, cfg: 2 },
  "illustrious-xl-v2.0": { width: 1024, height: 1024, steps: 30, cfg: 7 },
};

export function sceneModelStyles(modelId: string): SceneStyle[] {
  if (modelId === "dreamshaper-xl-lightning") return ["photo", "anime"];
  if (isIdentityModelId(modelId) || Object.hasOwn(generationRecipes, modelId)) return [defaultSceneStyle(modelId)];
  return [];
}

export function sceneRecipe(modelId: string, style: SceneStyle, registeredDefaults?: Partial<SceneRecipe>): SceneRecipe | null {
  if (!sceneModelStyles(modelId).includes(style)) return null;
  const base = isIdentityModelId(modelId) ? identityModelDefaults(modelId) : generationRecipes[modelId];
  // Whitelist the four recipe fields: never spread model, identity or sampler options.
  const { width, height, steps, cfg } = { ...base, ...registeredDefaults };
  return { width, height, steps, cfg };
}

export function defaultSceneStyle(modelId: string): SceneStyle {
  return modelId.startsWith("illustrious-") || modelId.startsWith("animagine-") || modelId === "cyberrealistic-xl-plus-face" ? "anime" : "photo";
}

export function scenePrompts(scene: ScenePreset, style: SceneStyle, framing: SceneFraming = "half"): ScenePrompts {
  const framingPrompts = {
    portrait: "head and shoulders portrait, face clearly visible",
    half: "medium shot, waist-up composition, face clearly visible",
    full: "full body, head to toe, feet in frame, wide composition, face visible",
  };
  const framingExclusions = {
    portrait: "cropped head",
    half: "tight close-up, cropped head",
    full: "close-up, waist-up, cropped head, cropped feet",
  };
  const subject = `solo adult woman, ${framingPrompts[framing]}`;
  const quality = style === "anime"
    ? "anime illustration, best quality, clean lineart, cel shading"
    : `realistic cinematic ${framing === "full" ? "photo" : "portrait photo"}, natural skin texture`;
  const excluded = "low quality, blurry, deformed face, bad anatomy, extra limbs, extra fingers, duplicate person, text, watermark";
  return {
    prompt: `${quality}, ${subject}, ${scene.prompt}`,
    negativePrompt: [excluded, style === "anime" ? "photorealistic, 3d, rough sketch, child, chibi" : "cartoon, anime, plastic skin", scene.negativePrompt, framingExclusions[framing]].filter(Boolean).join(", "),
  };
}
