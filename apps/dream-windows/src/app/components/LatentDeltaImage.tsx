import type { RuntimeLatentTelemetry } from "../../domain/trace";

export function LatentDeltaImage({ sample }: { sample: RuntimeLatentTelemetry }) {
  if (!sample.deltaImageUrl) {
    return <div className="unavailable-panel"><strong>空间 Δz 图不可用</strong><p>首个采样状态或旧记录未导出相邻原始浮点 Latent 的空间变化图。</p></div>;
  }
  return <div className="latent-preview-card">
    <div className="section-title">空间平均 |Δz| <span className="truth-label truth-derived">由实测 Latent 派生</span></div>
    <img className="latent-preview-image" src={sample.deltaImageUrl} alt={`第 ${sample.step + 1} 步空间平均 |Δz|`} loading="lazy" decoding="async" />
    <p>相邻已采集状态的原始浮点差值，按通道与批次取平均。色阶为零至当前图最大值；全零变化为黑色，跨步骤颜色不代表相同绝对强度。</p>
  </div>;
}
