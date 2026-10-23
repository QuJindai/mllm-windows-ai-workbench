import { useState } from "react";
import type { IdentityReference } from "../../../domain/identity";

export function FacePicker({ reference, selected, onSelect }: { reference: IdentityReference; selected: number | null; onSelect: (index: number) => void }) {
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  return <div className="identity-face-picker">
    <div className="identity-reference-image">
      <img src={reference.imageUrl} alt="参考照" onLoad={(event) => { const img = event.currentTarget; if (img.naturalWidth && img.naturalHeight) setSize({ width: img.naturalWidth, height: img.naturalHeight }); }} />
      {size && <svg viewBox={`0 0 ${size.width} ${size.height}`} aria-hidden="true">{reference.faces.map((face) => <g key={face.index} className={selected === face.index ? "is-selected" : ""}><rect x={face.box[0]} y={face.box[1]} width={face.box[2] - face.box[0]} height={face.box[3] - face.box[1]} /><text x={face.box[0]} y={face.box[1] + Math.max(16, size.width / 30)} fontSize={Math.max(16, size.width / 30)}>{face.index + 1}</text></g>)}</svg>}
    </div>
    {reference.faces.length > 1 && <p className="identity-note">检测到多张人脸，请按图中编号明确选择人物。</p>}
    {!reference.faces.length && <p className="identity-error">没有检测到人脸，请更换参考照。</p>}
    <div className="identity-face-options" role="radiogroup" aria-label="参考人物">{reference.faces.map((face) => <label key={face.index}><input type="radio" name="identity-face" checked={selected === face.index} onChange={() => onSelect(face.index)} />人脸 {face.index + 1}</label>)}</div>
  </div>;
}
