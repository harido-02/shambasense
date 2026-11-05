// Copies the web app into dist/ for Capacitor and points it at the hosted API.
//   SHAMBA_API_BASE=https://your-app.onrender.com node build-web.mjs
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");
const dist = join(here, "dist");
const api = (process.env.SHAMBA_API_BASE || "").replace(/\/$/, "");
if (!/^https:\/\//.test(api)) {
  console.error("Set SHAMBA_API_BASE to the hosted ShambaSense address, e.g. https://shambasense.onrender.com");
  process.exit(1);
}
rmSync(dist, { recursive: true, force: true });
mkdirSync(join(dist, "static"), { recursive: true });
for (const dir of ["css", "js", "vendor", "icons"]) cpSync(join(web, dir), join(dist, "static", dir), { recursive: true });
writeFileSync(join(dist, "static", "js", "runtime-config.js"), `window.SHAMBA_API_BASE = ${JSON.stringify(api)};\n`);
// The packaged app has no service worker or web manifest; Android provides install, icon and offline shell.
const html = readFileSync(join(web, "index.html"), "utf8")
  .replace(/\s*<link rel="manifest"[^>]*>/, "")
  .replace(/\s*<meta name="apple-mobile[^>]*>/g, "");
writeFileSync(join(dist, "index.html"), html);
console.log(`dist/ ready, API: ${api}`);
