import { useEffect, useState } from "react";
import { defaultSceneStyle, scenePresets, scenePrompts } from "../../domain/scene-presets";
import type { ScenePrompts, SceneStyle } from "../../domain/scene-presets";
import "./ScenePresetPicker.css";

type Props = ScenePrompts & { modelId: string; disabled?: boolean; onApply: (value: ScenePrompts) => void };

export function ScenePresetPicker({ modelId, prompt, negativePrompt, disabled = false, onApply }: Props) {
  const [style, setStyle] = useState<SceneStyle>(() => defaultSceneStyle(modelId));
  const [last, setLast] = useState<{ name: string; before: ScenePrompts; after: ScenePrompts } | null>(null);
  useEffect(() => { setStyle(defaultSceneStyle(modelId)); }, [modelId]);
  const unchanged = last && prompt === last.after.prompt && negativePrompt === last.after.negativePrompt;

  return <fieldset className="scene-presets" disabled={disabled}>
    <legend>场景预设</legend>
    <div className="scene-presets-heading">
      <p>选择场景填入正、负提示词，保留当前人物和生成参数。</p>
      <label>场景画风<select value={style} onChange={event => setStyle(event.target.value as SceneStyle)}>
        <option value="photo">写实</option><option value="anime">动漫插画</option>
      </select></label>
    </div>
    <div className="scene-presets-grid">{scenePresets.map(scene => <button key={scene.id} type="button"
      className="secondary-button scene-preset" aria-label={`应用${scene.name}场景`}
      onClick={() => {
        const after = scenePrompts(scene, style);
        setLast({ name: scene.name, before: { prompt, negativePrompt }, after });
        onApply(after);
      }}><strong>{scene.name}</strong><span>{scene.description}</span></button>)}</div>
    <div className="scene-presets-footer">
      <small>画风提示需配合所选模型；可继续修改服装、背景和姿态。</small>
      {unchanged && <><span role="status">已应用{last.name}场景</span><button type="button" className="secondary-button" onClick={() => { onApply(last.before); setLast(null); }}>撤销场景替换</button></>}
    </div>
  </fieldset>;
}
