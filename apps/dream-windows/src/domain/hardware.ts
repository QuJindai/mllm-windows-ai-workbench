export type TruthLevel = "observed" | "derived" | "unavailable" | "demo";

export type HardwareSnapshot = {
  gpuName: string;
  vramTotalMiB: number;
  vramUsedMiB: number;
  gpuUtil: number;
  gpuTempC?: number;
  gpuPowerW?: number;
  ramTotalBytes: number;
  ramUsedBytes: number;
  cudaReady: boolean;
  dreamRoot: string;
  truth: TruthLevel;
  isMock: boolean;
  cpuName?: string;
  cpuCores?: number;
  cpuThreads?: number;
  driverVersion?: string;
  eDriveTotalBytes?: number;
  eDriveFreeBytes?: number;
};
