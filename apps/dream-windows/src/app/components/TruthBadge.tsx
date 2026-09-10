import type { TruthLevel } from "../../domain/hardware";

const labels: Record<TruthLevel, string> = {
  observed: "实测",
  derived: "派生",
  unavailable: "不可用",
  demo: "演示",
};

export function TruthBadge({ truth, label }: { truth: TruthLevel; label?: string }) {
  return <span className={`truth-label truth-${truth}`}>{label ?? labels[truth]}</span>;
}
