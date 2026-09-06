import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const frontendDist = "E:/Dream/builds/dream-windows/frontend";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: frontendDist,
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    globals: true,
  },
});
