import { useState } from "react";
import type { RuntimeLatentTelemetry } from "../../domain/trace";

type Props = { previous?: RuntimeLatentTelemetry; current: RuntimeLatentTelemetry; final: RuntimeLatentTelemetry };

export function SelectedChannelComparison({ previous, current, final }: Props) {
  const [selected, setSelected] = useState(0);
  const entries = [{ label: "上一步", sample: previous }, { label: "当前", sample: current }, { label: "最终", sample: final }];
  const channels = [...new Set(entries.flatMap(({ sample }) => sample?.channels.filter((channel) => channel.truth === "observed").map((channel) => channel.channel) ?? []))].sort((a, b) => a - b);
  const channelId = channels.includes(selected) ? selected : channels[0];
  if (channelId === undefined) return <div className="unavailable-panel">通道对比不可用</div>;
  return <div className="latent-table-wrap" style={{ overflowX: "auto" }}>
    <label>选择对比通道 <select aria-label="选择对比通道" value={channelId} onChange={(event) => setSelected(Number(event.target.value))}>
      {channels.map((id) => <option key={id} value={id}>C{id}</option>)}
    </select></label>
    <table className="latent-stats-table">
      <caption>C{channelId} 上一步、当前与最终统计</caption>
      <thead><tr><th scope="col">采样状态</th><th scope="col">最小</th><th scope="col">最大</th><th scope="col">均值</th><th scope="col">标准差</th><th scope="col">L2</th></tr></thead>
      <tbody>{entries.map(({ label, sample }) => {
        const channel = sample?.channels.find((item) => item.channel === channelId && item.truth === "observed");
        return <tr key={label}>
          <th scope="row">{label}{sample ? ` 第 ${sample.step + 1} 步` : ""}</th>
          {channel ? ([channel.min, channel.max, channel.mean, channel.std, channel.l2].map((value, index) =>
            <td key={index}>{Number.isFinite(value) ? value.toFixed(4) : "—"}</td>)) : <td colSpan={5}>{sample ? "通道未采集" : "尚未采集"}</td>}
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
