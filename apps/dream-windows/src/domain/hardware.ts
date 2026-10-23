export type TruthLevel = "observed" | "derived" | "unavailable" | "demo";

export type HardwareSnapshot = {
  gpuName: string;
  vramTotalMiB: number;
  vramUsedMiB: number;
  gpuUtil: number;
  gpuTempC?: number | null;
  gpuPowerW?: number | null;
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
  sampledAt?: string;
  telemetrySource?: string;
};

export const HARDWARE_MAX_AGE_MS = 10_000;

export function isFreshHardware(snapshot: HardwareSnapshot, now = Date.now()): boolean {
  const sampled = Date.parse(snapshot.sampledAt ?? "");
  return Number.isFinite(sampled) && sampled <= now + 1000 && now - sampled < HARDWARE_MAX_AGE_MS;
}
