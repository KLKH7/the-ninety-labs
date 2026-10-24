import { resolve } from "node:path";
import { defineConfig } from "vite";

// In development the companion API runs beside this server (NINETY_COMPANION=standin uv run uvicorn
// ninety.api.app:app --port 8000); /api, the WebSocket relay included, goes to it. Deployed, the API
// serves this build at /phone/, so the phone and the API share one origin.
const API = process.env.NINETY_API ?? "http://127.0.0.1:8000";

function pages(mock: boolean): Record<string, string> {
  const input: Record<string, string> = { phone: resolve(__dirname, "index.html") };
  if (mock) input.laptop = resolve(__dirname, "mock-laptop.html");
  return input;
}

// `vite build` is what ships: the phone alone. `vite build --mode mock` (and `vite`, the dev server)
// adds the mock feed and the mock laptop page, into dist-mock/, for building and testing without a
// server; the mock never reaches the production bundle.
export default defineConfig(({ mode, command }) => {
  const mock = mode === "mock" || command === "serve";
  return {
    base: "./",
    publicDir: false,
    // The radar, the match and the club names are the viewer's own modules (../viewer/src), so the
    // phone and the big screen draw and name things one way.
    server: { proxy: { "/api": { target: API, ws: true } }, fs: { allow: [resolve(__dirname, ".."), resolve(__dirname, "../viewer/src")] } },
    define: { __PHONE_MOCK__: JSON.stringify(mock) }, // src/env.d.ts
    build: {
      outDir: mock ? "dist-mock" : "dist",
      emptyOutDir: true,
      target: "es2022",
      rollupOptions: { input: pages(mock) },
    },
  };
});
