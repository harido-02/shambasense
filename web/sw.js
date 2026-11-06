// ShambaSense service worker: the app opens offline, and the last advice, prices and weather
// are shown (marked as saved copies) when there is no connection.
const VERSION = "shambasense-v4";
const SHELL = [
  "/", "/manifest.webmanifest",
  "/static/css/app.css", "/static/js/app.js", "/static/js/api.js", "/static/js/charts.js", "/static/js/config.js",
  "/static/js/i18n.js", "/static/js/map.js", "/static/js/results.js", "/static/js/runtime-config.js",
  "/static/js/store.js", "/static/js/ui.js", "/static/js/views/account.js", "/static/js/views/advice.js",
  "/static/js/views/farms.js", "/static/js/views/prices.js", "/static/js/views/weather.js",
  "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css",
  "/static/vendor/leaflet/images/marker-icon.png", "/static/vendor/leaflet/images/marker-icon-2x.png",
  "/static/vendor/leaflet/images/marker-shadow.png",
  "/static/vendor/fonts/archivo-latin-wdth-normal.woff2",
  "/static/icons/icon.svg", "/static/icons/icon-192.png", "/static/icons/icon-512.png",
];
const API_CACHE = "shambasense-api";
const CACHEABLE_API = /^\/(health|api\/(counties|crops|recommend|prices|weather|farms|me|reminders))/;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((k) => k !== VERSION && k !== API_CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  // API reads: network first; on failure, the last saved copy, marked with when it was saved.
  if (CACHEABLE_API.test(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(API_CACHE);
      const key = req.url + "|" + (req.headers.get("Authorization") || "").slice(-12);
      try {
        const res = await fetch(req);
        if (res.ok) {
          const copy = res.clone();
          const headers = new Headers(copy.headers);
          headers.set("X-Shamba-Cached", new Date().toISOString().slice(0, 16).replace("T", " "));
          cache.put(key, new Response(await copy.blob(), { status: copy.status, headers }));
        }
        return res;
      } catch (err) {
        const hit = await cache.match(key);
        if (hit) return hit;
        throw err;
      }
    })());
    return;
  }

  // App shell and static files: cache first, refresh in the background.
  if (url.pathname === "/" || url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith((async () => {
      const cache = await caches.open(VERSION);
      const hit = await cache.match(url.pathname === "/" ? "/" : req);
      const network = fetch(req).then((res) => { if (res.ok) cache.put(url.pathname === "/" ? "/" : req, res.clone()); return res; }).catch(() => null);
      return hit || (await network) || new Response("Offline", { status: 503 });
    })());
  }
});
