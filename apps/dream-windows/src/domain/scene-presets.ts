import scenes from "./scene-presets.json";

export const scenePresets = scenes;
export type ScenePreset = typeof scenes[number];
export type SceneStyle = "photo" | "anime";
export type ScenePrompts = { prompt: string; negativePrompt: string };

export function defaultSceneStyle(modelId: string): SceneStyle {
  return modelId.startsWith("illustrious-") || modelId.startsWith("animagine-") || modelId === "cyberrealistic-xl-plus-face" ? "anime" : "photo";
}

export function scenePrompts(scene: ScenePreset, style: SceneStyle): ScenePrompts {
  const subject = "solo adult woman, medium shot, face clearly visible";
  const quality = style === "anime"
    ? "masterpiece, best quality, anime illustration, clean lineart, cel shading, 1girl"
    : "realistic cinematic portrait photo, natural skin texture";
  const excluded = "low quality, blurry, deformed face, bad anatomy, extra limbs, extra fingers, duplicate person, text, watermark";
  return {
    prompt: `${quality}, ${subject}, ${scene.prompt}`,
    negativePrompt: [excluded, style === "anime" ? "photorealistic, 3d, rough sketch, child, chibi" : "cartoon, anime, plastic skin", scene.negativePrompt].filter(Boolean).join(", "),
  };
}
