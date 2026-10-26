import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, resolve, sep } from "node:path";
import { defineConfig, type Plugin } from "vite";

// The bundle `ninety-e2e` wrote, served at /bundle/ (NINETY_BUNDLE, default runs/e2e/seed900001).
const BUNDLE = resolve(process.env.NINETY_BUNDLE ?? resolve(__dirname, "../../runs/e2e/seed900001"));
const TYPES: Record<string, string> = {
  ".json": "application/json",
  ".jsonl": "application/x-ndjson",
  ".webm": "video/webm",
  ".mp4": "video/mp4",
  ".m3u8": "application/vnd.apple.mpegurl",
  ".m4s": "video/iso.segment",
  ".jpg": "image/jpeg",
  ".wav": "audio/wav",
  ".vtt": "text/vtt",
};

/** Serves the bundle with byte ranges, so the video seeks. Read-only, and never outside BUNDLE. */
function bundle(): Plugin {
  return {
    name: "ninety-bundle",
    configureServer(server) {
      server.middlewares.use("/bundle/", (req, res, next) => {
        const path = resolve(BUNDLE, decodeURIComponent((req.url ?? "/").split("?")[0]).replace(/^\/+/, ""));
        if (!(path + sep).startsWith(BUNDLE + sep) && path !== BUNDLE) return next();
        if (!existsSync(path) || !statSync(path).isFile()) return next();
        const size = statSync(path).size;
        res.setHeader("Content-Type", TYPES[extname(path)] ?? "application/octet-stream");
        res.setHeader("Accept-Ranges", "bytes");
        const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? "");
        if (range) {
          const start = range[1] ? Number(range[1]) : 0;
          const end = range[2] ? Math.min(Number(range[2]), size - 1) : size - 1;
          res.statusCode = 206;
          res.setHeader("Content-Range", `bytes ${start}-${end}/${size}`);
          res.setHeader("Content-Length", end - start + 1);
          createReadStream(path, { start, end }).pipe(res);
          return;
        }
        res.setHeader("Content-Length", size);
        createReadStream(path).pipe(res);
      });
    },
  };
}

export default defineConfig({
  base: "./",
  publicDir: false,
  plugins: [bundle()],
  build: { outDir: "dist", emptyOutDir: true },
});
