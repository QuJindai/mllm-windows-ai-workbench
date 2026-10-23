import type { RuntimeLatentTelemetry } from "../../domain/trace";

function isCorrelationMatrix(value: unknown, channels: number): value is (number | null)[][] {
  if (!Number.isInteger(channels) || channels < 1 || channels > 16 || !Array.isArray(value) || value.length !== channels) return false;
  if (!value.every((row) => Array.isArray(row) && row.length === channels && row.every((cell: unknown) =>
    cell === null || (typeof cell === "number" && Number.isFinite(cell) && cell >= -1 && cell <= 1)))) return false;
  return value.every((row, left) => (row[left] === null || Math.abs(row[left] - 1) <= 1e-12) && row.every((cell: number | null, right: number) =>
    cell === value[right][left] && (cell === null) === (row[left] === null || value[right][right] === null)));
}

export function CorrelationMatrix({ sample }: { sample: RuntimeLatentTelemetry }) {
  const matrix = sample.channelCorrelation;
  if (!isCorrelationMatrix(matrix, sample.shape[2] ?? 1) || sample.correlationMethod !== "pearson") {
    const channels = sample.shape[2] ?? 1;
    return <div className="unavailable-panel"><strong>通道相关性不可用</strong><p>当前 trace 未导出实测的 {channels} × {channels} 通道相关矩阵。</p></div>;
  }

  return (
    <div className="latent-table-wrap" style={{ overflowX: "auto" }}>
      <table className="latent-stats-table">
        <caption>第 {sample.step + 1} 步 · Pearson 通道相关矩阵</caption>
        <thead><tr><th scope="col">通道</th>{matrix.map((_, channel) => <th scope="col" key={channel}>C{channel}</th>)}</tr></thead>
        <tbody>{matrix.map((row, left) => (
          <tr key={left}>
            <th scope="row">C{left}</th>
            {row.map((value, right) => (
              <td key={right} aria-label={`C${left} 与 C${right}：${value === null ? "未定义" : value.toFixed(4)}`}
                style={{ backgroundColor: value === null ? undefined : `rgba(${value < 0 ? "219, 92, 77" : "55, 145, 208"}, ${Math.abs(value) * .22})` }}>
                {value === null ? "—" : value.toFixed(4)}
              </td>
            ))}
          </tr>
        ))}</tbody>
      </table>
      <p><span className="truth-label truth-derived">由实测原始浮点 Latent 派生</span> · 全部批次与空间位置 · Pearson −1 至 +1；— 表示零方差或非有限值导致相关性未定义。</p>
    </div>
  );
}
