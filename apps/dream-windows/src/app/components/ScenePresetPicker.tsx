import { useEffect, useState } from "react";
import { defaultSceneStyle, sceneModelStyles, scenePresets, scenePrompts, sceneRecipe } from "../../domain/scene-presets";
import type { SceneFraming, ScenePrompts, SceneRecipe, SceneStyle } from "../../domain/scene-presets";
import "./ScenePresetPicker.css";

type Props = ScenePrompts & {
  modelId: string;
  modelName?: string;
  modelReady?: boolean;
  recipeDefaults?: Partial<SceneRecipe>;
  disabled?: boolean;
  onApply: (value: ScenePrompts) => void;
  onApplyRecipe?: (value: SceneRecipe) => void;
};

export function ScenePresetPicker({ modelId, modelName, modelReady = false, recipeDefaults, prompt, negativePrompt, disabled = false, onApply, onApplyRecipe }: Props) {
  const [style, setStyle] = useState<SceneStyle>(() => defaultSceneStyle(modelId));
  const [framing, setFraming] = useState<SceneFraming>("half");
  const [last, setLast] = useState<{ name: string; before: ScenePrompts; after: ScenePrompts } | null>(null);
  useEffect(() => { setStyle(defaultSceneStyle(modelId)); }, [modelId]);
  const unchanged = last && prompt === last.after.prompt && negativePrompt === last.after.negativePrompt;
  const recipe = sceneRecipe(modelId, style, recipeDefaults);
  const modelStyles = sceneModelStyles(modelId).map(value => value === "photo" ? "写实" : "动漫插画").join(" / ");

  return <fieldset className="scene-presets" disabled={disabled}>
    <legend>场景预设</legend>
    <div className="scene-presets-heading">
      <p>选择构图和画风后，点击场景仅填入正、负提示词，保留当前人物和生成参数。</p>
      <label>场景画风<select value={style} onChange={event => setStyle(event.target.value as SceneStyle)}>
        <option value="photo">写实</option><option value="anime">动漫插画</option>
      </select></label>
      <label>场景构图<select value={framing} onChange={event => setFraming(event.target.value as SceneFraming)}>
        <option value="portrait">肖像 · 头肩</option><option value="half">半身 · 腰部以上</option><option value="full">全身 · 头到脚</option>
      </select></label>
    </div>
    <div className="scene-presets-grid">{scenePresets.map(scene => <button key={scene.id} type="button"
      className="secondary-button scene-preset" aria-label={`应用${scene.name}场景`}
      onClick={() => {
        const after = scenePrompts(scene, style, framing);
        setLast({ name: scene.name, before: { prompt, negativePrompt }, after });
        onApply(after);
      }}><strong>{scene.name}</strong><span>{scene.description}</span></button>)}</div>
    <div className="scene-presets-footer">
      <small>文本构图提示，不是骨架约束；不保证姿态、手脚或完整入镜，可继续修改服装和背景。</small>
      {unchanged && <><span role="status">已应用{last.name}场景</span><button type="button" className="secondary-button" onClick={() => { onApply(last.before); setLast(null); }}>撤销场景替换</button></>}
    </div>
    {onApplyRecipe && <div className="scene-recipe">
      <p>当前模型：{modelName ?? modelId}{modelStyles && `（${modelStyles}）`}</p>
      {recipe && <p className="scene-recipe-values">模型推荐：{recipe.width} × {recipe.height} · {recipe.steps} 步 · CFG {recipe.cfg}</p>}
      <p>单独应用仅替换尺寸、步数和 CFG。采样器、种子、人物引用与修脸设置保留；所选构图仍以提示词表达。</p>
      {!modelReady ? <p>当前模型未就绪，推荐参数不可用。</p>
        : !recipe && <p>当前模型与画风没有兼容的推荐参数，可继续仅应用提示词。</p>}
      <button type="button" className="secondary-button" disabled={!modelReady || !recipe}
        onClick={() => { if (!disabled && modelReady && recipe) onApplyRecipe(recipe); }}>应用模型推荐参数</button>
    </div>}
  </fieldset>;
}
