import { spawnSync } from "node:child_process";
import path from "node:path";

const dreamRoot = "E:\\Dream";
const env = {
  ...process.env,
  npm_config_cache: path.join(dreamRoot, "cache", "npm"),
  CARGO_HOME: path.join(dreamRoot, "cache", "cargo"),
  CARGO_TARGET_DIR: path.join(dreamRoot, "builds", "dream-windows"),
};
const executable = process.platform === "win32" ? "tauri.cmd" : "tauri";
const result = spawnSync(executable, process.argv.slice(2), { env, stdio: "inherit", shell: process.platform === "win32" });

if (result.error) {
  console.error(`Unable to start ${executable}: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
