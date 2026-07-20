import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["tests/**/*.test.ts?(x)"],
    exclude: ["tests-e2e/**"]
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname)
    }
  }
});
