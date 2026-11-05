// Thin client for the ShambaSense API: adds the sign-in token, turns errors into messages,
// and marks responses the service worker served from its offline copy.
import { API_BASE } from "./config.js";
import { store } from "./store.js";
import { t } from "./i18n.js";

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function detail(data) {
  if (!data || !data.detail) return null;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).join(". ");
  return null;
}

export async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && store.token) headers.Authorization = `Bearer ${store.token}`;
  let res;
  try {
    res = await fetch(API_BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(t("offline_error"), 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    if (res.status === 401 && store.token && !path.startsWith("/api/auth")) store.signOutLocal();
    throw new ApiError(detail(data) || t("error_generic"), res.status);
  }
  const cachedAt = res.headers.get("X-Shamba-Cached");
  if (cachedAt && data && typeof data === "object") Object.defineProperty(data, "cachedAt", { value: cachedAt });
  return data;
}

export const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") p.set(k, v); });
  return p.toString();
};
