import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = path.resolve(import.meta.dirname, "..");

describe("Dream build policy", () => {
  it("routes the Tauri command through the E-drive build launcher", () => {
    const packageJson = JSON.parse(fs.readFileSync(path.join(appRoot, "package.json"), "utf8")) as { scripts: Record<string, string> };
    expect(packageJson.scripts["tauri:build"]).toContain("run-tauri.mjs build");
    expect(packageJson.scripts["tauri:dev"]).toContain("run-tauri.mjs dev");
  });

  it("keeps the launcher and Tauri output policy rooted at E:\\Dream", () => {
    const launcher = fs.readFileSync(path.join(appRoot, "scripts/run-tauri.mjs"), "utf8");
    const vite = fs.readFileSync(path.join(appRoot, "vite.config.ts"), "utf8");
    const tauri = fs.readFileSync(path.join(appRoot, "src-tauri/tauri.conf.json"), "utf8");
    expect(launcher).toContain('E:\\\\Dream');
    expect(launcher).toContain("CARGO_TARGET_DIR");
    expect(launcher).toContain('path.join(dreamRoot, "builds", "dream-windows")');
    expect(launcher).toContain('shell: process.platform === "win32"');
    expect(vite).toContain('E:/Dream/builds/dream-windows/frontend');
    expect(tauri).toContain('"frontendDist": "E:/Dream/builds/dream-windows/frontend"');
  });
});
