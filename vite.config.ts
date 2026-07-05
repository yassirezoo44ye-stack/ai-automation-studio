/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000
  },
  resolve: {
    alias: {
      "@shared":   resolve(__dirname, "src/renderer/shared"),
      "@features": resolve(__dirname, "src/renderer/features"),
      "@core":     resolve(__dirname, "src/renderer/core"),
      "@app":      resolve(__dirname, "src/renderer/app"),
    }
  },
  build: {
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom"],
          markdown: ["react-markdown"],
          fabric: ["fabric"],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/renderer/__tests__/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/renderer/shared/**", "src/renderer/contexts/**"],
    },
  },
});