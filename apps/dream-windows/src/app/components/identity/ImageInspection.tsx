import { useState } from "react";
import "./ImageInspection.css";

export type ImageDimensions = { width: number; height: number };
type Props = { src: string; alt: string; onError: () => void; onDimensions?: (size: ImageDimensions) => void };

// A different original/version starts in fit mode with its own decoded dimensions.
export function ImageInspection(props: Props) {
  return <ImageInspectionView key={props.src} {...props} />;
}

function ImageInspectionView({ src, alt, onError, onDimensions }: Props) {
  const [dimensions, setDimensions] = useState<ImageDimensions | null>(null);
  const [scale, setScale] = useState<"fit" | 1 | 2>("fit");
  const fit = scale === "fit" || !dimensions;
  return <div className="image-inspection">
    <div className="image-inspection-controls" role="group" aria-label={`${alt}查看方式`}>
      <button type="button" className="secondary-button" aria-pressed={scale === "fit"} onClick={() => setScale("fit")}>适应窗口</button>
      <button type="button" className="secondary-button" aria-pressed={scale === 1} disabled={!dimensions} onClick={() => setScale(1)}>100% 原始尺寸</button>
      <button type="button" className="secondary-button" aria-pressed={scale === 2} disabled={!dimensions} onClick={() => setScale(2)}>200% 放大查看</button>
      <a className="secondary-button" href={src} target="_blank" rel="noreferrer" aria-label={`${alt}：打开原图 / 放大查看`}>打开原图 / 放大查看</a>
    </div>
    <p className="image-inspection-note">{dimensions ? `文件尺寸：${dimensions.width} × ${dimensions.height} 像素。` : "文件尺寸读取中。"}200% 仅放大显示，不增加图像细节。</p>
    <div className="image-inspection-viewport" tabIndex={0} role="region" aria-label={`${alt}图像区域`}>
      <a href={src} target="_blank" rel="noreferrer"><img src={src} alt={alt} decoding="async" onError={onError}
        style={{ display: "block", width: fit ? "auto" : `${dimensions.width * (scale as number)}px`, height: "auto", aspectRatio: "auto",
          maxWidth: fit ? "100%" : "none", maxHeight: fit ? "min(70vh, 768px)" : "none", margin: "0 auto" }}
        onLoad={event => {
          const { naturalWidth: width, naturalHeight: height } = event.currentTarget;
          if (width > 0 && height > 0) { setDimensions({ width, height }); onDimensions?.({ width, height }); }
        }} /></a>
    </div>
  </div>;
}
