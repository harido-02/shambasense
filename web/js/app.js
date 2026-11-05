// App shell: navigation, routing, language, offline state, install prompt and service worker.
import { api } from "./api.js";
import { IS_NATIVE } from "./config.js";
import { t } from "./i18n.js";
import { store } from "./store.js";
import { $, $$, esc, hideToast, icon } from "./ui.js";
import { accountView, historyItem } from "./views/account.js";
import { adviceView } from "./views/advice.js";
import { farmDetail, farmNew, farmsList } from "./views/farms.js";
import { priceDetail, pricesView } from "./views/prices.js";
import { weatherView } from "./views/weather.js";

const ROUTES = [
  [/^$/, adviceView, "advice"],
  [/^farms$/, farmsList, "farms"],
  [/^farms\/new$/, farmNew, "farms"],
  [/^farms\/(\d+)$/, farmDetail, "farms"],
  [/^prices$/, pricesView, "prices"],
  [/^prices\/([a-z_]+)$/, priceDetail, "prices"],
  [/^weather$/, weatherView, "weather"],
  [/^me$/, accountView, "me"],
  [/^me\/history\/(\d+)$/, historyItem, "me"],
];
const NAV = [["advice", "#/", "sprout", "nav_advice"], ["farms", "#/farms", "farm", "nav_farms"],
  ["prices", "#/prices", "tag", "nav_prices"], ["weather", "#/weather", "rain", "nav_weather"], ["me", "#/me", "user", "nav_me"]];

function renderChrome(section) {
  document.documentElement.lang = store.lang;
  $("#nav").innerHTML = `<a class="wordmark wordmark-side" href="#/">Shamba<span>Sense</span></a>` + NAV.map(([key, href, ic, label]) =>
    `<a href="${href}" ${key === section ? 'aria-current="page"' : ""}>${icon(ic)}<span>${esc(t(label))}</span></a>`).join("");
  $$(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === store.lang)));
  const me = $("#me-button");
  me.dataset.signedIn = String(Boolean(store.user));
  me.textContent = store.user ? (store.user.name || "•").trim().charAt(0).toUpperCase() : "";
  if (!store.user) me.innerHTML = icon("user");
  me.setAttribute("aria-label", store.user ? t("nav_me") : t("sign_in"));
  const demo = store.health && store.health.data_quality === "synthetic";
  $("#banner-demo").hidden = !demo;
  $("#banner-demo").textContent = t("demo");
  $("#banner-offline").hidden = store.online;
  $("#banner-offline").textContent = t("offline_banner");
}

let rendering = 0;
async function route() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, q = ""] = raw.split("?");
  const query = new URLSearchParams(q);
  const match = ROUTES.map(([re, view, section]) => [path.match(re), view, section]).find(([m]) => m) || [[""], adviceView, "advice"];
  const [m, view, section] = match;
  renderChrome(section);
  hideToast();
  const main = $("#main");
  const id = ++rendering;
  try {
    await view(main, m.slice(1), query);
  } catch (err) {
    if (id === rendering) main.innerHTML = `<p class="error">${esc(err.message || t("error_generic"))}</p>`;
  }
  if (id === rendering) {
    main.focus({ preventScroll: true });
    if (!location.hash.includes("#/me/history") && !q) window.scrollTo(0, 0);
  }
}

async function boot() {
  $$(".lang button").forEach((b) => b.addEventListener("click", () => {
    store.set({ lang: b.dataset.lang });
    if (store.user) api("/api/me", { method: "PATCH", body: { lang: b.dataset.lang } }).catch(() => {});
    route();
  }));
  window.addEventListener("hashchange", route);
  window.addEventListener("online", () => { store.online = true; renderChrome(currentSection()); });
  window.addEventListener("offline", () => { store.online = false; renderChrome(currentSection()); });
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); store.installPrompt = e; });

  const main = $("#main");
  main.innerHTML = `<p class="loading">${esc(t("loading"))}</p>`;
  try {
    const [counties, crops, health] = await Promise.all([api("/api/counties", { auth: false }), api("/api/crops", { auth: false }),
      api("/health", { auth: false }).catch(() => null)]);
    Object.assign(store, { counties, crops, health });
  } catch (err) {
    main.innerHTML = `<div class="empty"><strong>${esc(t("cannot_reach"))}</strong>${esc(err.message)}</div>`;
    renderChrome("advice");
    return;
  }
  if (store.token) api("/api/me").then((user) => { store.set({ user }); renderChrome(currentSection()); }).catch(() => {});
  route();
  if ("serviceWorker" in navigator && !IS_NATIVE && location.protocol !== "file:") {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

function currentSection() {
  const path = location.hash.replace(/^#\/?/, "").split("?")[0];
  const hit = ROUTES.find(([re]) => re.test(path));
  return hit ? hit[2] : "advice";
}

boot();
