import "./research-artifacts.css";

export function researchMessage(message: string): string {
  if (/[\u3400-\u9fff]/.test(message)) return message;
  if (/invalid|malformed|validation|mismatch/i.test(message)) return "研究记录无效或校验未通过，请检查采集产物后刷新。";
  if (/not found|missing|no validated|not available|unavailable/i.test(message)) return "当前运行没有可用的研究产物，请选择兼容记录或完成相应研究采集后刷新。";
  return "研究数据读取失败，请在后端部署完成后刷新记录。";
}

export function RawMetric({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{String(value)}</strong></div>;
}

export function ResearchSpatialMap({ label, width, height, values, zeroBaseline = false, queryIndex }: {
  label: string; width: number; height: number; values: number[]; zeroBaseline?: boolean; queryIndex?: number;
}) {
  const range = values.reduce((result, value) => ({ min: Math.min(result.min, value), max: Math.max(result.max, value) }), { min: Infinity, max: -Infinity });
  const minimum = zeroBaseline ? 0 : range.min;
  const span = range.max - minimum;
  return <figure className="research-map-figure">
    <div className="research-spatial-map" role="img" aria-label={label} data-attention-heatmap="observed" style={{ gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))`, gridTemplateRows: `repeat(${height}, minmax(0, 1fr))`, aspectRatio: `${width} / ${height}` }}>
      {values.map((value, cell) => {
        const intensity = span > 0 ? (value - minimum) / span : 0;
        return <span key={cell} aria-hidden="true" data-raw-value={value} data-display-intensity={intensity} className={cell === queryIndex ? "is-query-anchor" : undefined} title={`位置 (${cell % width}, ${Math.floor(cell / width)}) · 原始值 ${value}${cell === queryIndex ? " · 查询锚点" : ""}`} style={{ background: `hsl(${232 - intensity * 232} 92% ${18 + intensity * 42}%)` }} />;
      })}
    </div>
    <figcaption>{width} × {height} 网格；原始范围 {String(range.min)}–{String(range.max)}。色阶仅用于显示，按{zeroBaseline ? "零到当前图最大值" : "当前图最小值到最大值"}缩放，不改变原始值。{span === 0 && "等值图使用统一色阶。"}{queryIndex !== undefined && "白框标记查询锚点。"}</figcaption>
  </figure>;
}
