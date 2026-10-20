import { resolve } from "node:path";
import { defineConfig } from "vite";

// In development the companion API runs beside this server (NINETY_COMPANION=standin uv run uvicorn
// ninety.api.app:app --port 8000); /api, the WebSocket relay included, goes to it. Deployed, the API
// serves this build at /phone/, so the phone and the API share one origin.
const API = process.env.NINETY_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  base: "./",
  publicDir: false,
  server: { proxy: { "/api": { target: API, ws: true } } },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: { input: { phone: resolve(__dirname, "index.html"), laptop: resolve(__dirname, "mock-laptop.html") } },
  },
});
