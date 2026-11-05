// Where the API lives. Empty means "same server as this page" (the web app).
// The Android build writes the hosted server's address into runtime-config.js.
export const API_BASE = String(window.SHAMBA_API_BASE || "").replace(/\/$/, "");
export const IS_NATIVE = Boolean(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
export const KENYA = { south: -4.8, north: 5.2, west: 33.8, east: 42.0 };
export const HA_PER_ACRE = 0.404686;
