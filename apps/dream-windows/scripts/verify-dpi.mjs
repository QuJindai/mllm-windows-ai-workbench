import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const css = fs.readFileSync(path.join(root, "src/app/shell.css"), "utf8");
const config = JSON.parse(fs.readFileSync(path.join(root, "src-tauri/tauri.conf.json"), "utf8"));
const checks = [
  ["responsive min width", config.app.windows[0].minWidth >= 960],
  ["responsive min height", config.app.windows[0].minHeight >= 640],
  ["fluid content sizing", css.includes("clamp(")],
  ["compact breakpoint", css.includes("@media (max-width: 850px)")],
  ["mobile breakpoint", css.includes("@media (max-width: 520px)")],
];
for (const [label, passed] of checks) console.log(`${passed ? "PASS" : "FAIL"} ${label}`);
if (checks.some(([, passed]) => !passed)) process.exit(1);
