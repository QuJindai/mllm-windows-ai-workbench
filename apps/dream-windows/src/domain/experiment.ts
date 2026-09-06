export type ExperimentVariant = {
  id: string;
  label: string;
  imageUrl: string;
  metric: number;
};

export type Experiment = {
  id: string;
  kind: "fusion" | "steps" | "model";
  seed: number;
  lockedFields: string[];
  variants: ExperimentVariant[];
};
