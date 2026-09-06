import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const files = [
  "package.json",
  "README.md",
  "vite.config.ts",
  "src-tauri/tauri.conf.json",
  "scripts/run-tauri.mjs",
  "src/fixtures/hardware.json",
  "src/fixtures/models.json",
  "src/fixtures/history.json",
  "src/app/App.tsx",
  "src/app/pages/GeneratePage.tsx",
  "src/app/pages/ModelsPage.tsx",
  "src/app/pages/HistoryPage.tsx",
];
const forbidden = /(?:C:\\Users|C:\\Dream|file:\/\/\/C:)/i;
let failed = false;
for (const relative of files) {
  const content = fs.readFileSync(path.join(root, relative), "utf8");
  const requiredPath = relative === "vite.config.ts" || relative === "src-tauri/tauri.conf.json";
  const passed = !forbidden.test(content)
    && (relative.includes("fixtures") || relative === "scripts/run-tauri.mjs" ? content.includes("E:\\\\Dream") : true)
    && (!requiredPath || content.includes("E:/Dream/builds/dream-windows/frontend"));
  console.log(`${passed ? "PASS" : "FAIL"} ${relative}`);
  failed ||= !passed;
}
if (failed) process.exit(1);
