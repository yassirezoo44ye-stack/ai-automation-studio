/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// ── Build-time guard for split-deploy misconfiguration ──────────────────────
// Vercel automatically sets VERCEL=1 during its builds. If VITE_API_URL is
// empty on Vercel the SPA will silently send every API call to the Vercel
// origin (not the Render backend) — 404 on every request, no data, no auth.
// This plugin prints an actionable warning so the problem is caught in the
// build log rather than discovered at runtime.
const warnMissingApiUrl = {
  name: "warn-missing-api-url",
  buildStart() {
    if (process.env.VERCEL && !process.env.VITE_API_URL) {
      console.warn(
        "\n⚠️  WARNING: VITE_API_URL is not set in Vercel environment variables.\n" +
        "   All API calls will fail because they go to the Vercel URL, not the backend.\n" +
        "   Fix: Vercel dashboard → Settings → Environment Variables →\n" +
        "        VITE_API_URL = https://ai-automation-studio.onrender.com\n" +
        "   Also set EXTRA_CORS_ORIGINS on Render to this Vercel domain.\n",
      );
    }
  },
};

export default defineConfig({
  plugins: [react(), warnMissingApiUrl],
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