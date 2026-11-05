// Market prices: latest wholesale price per crop with 12-month change, and a 3-year chart per crop.
import { api, qs } from "../api.js";
import { priceChart, sparkline } from "../charts.js";
import { t } from "../i18n.js";
import { store } from "../store.js";
import { $, esc, icon, loading, monthYear, num, pct } from "../ui.js";

function countyChips(current, base) {
  return `<div class="chips" style="margin-bottom:1.25rem" role="group" aria-label="${esc(t("counties"))}">
    <a class="chip ${!current ? "active" : ""}" href="${base}">${esc(t("all_kenya"))}</a>
    ${store.counties.map((c) => `<a class="chip ${current === c.id ? "active" : ""}" href="${base}${base.includes("?") ? "&" : "?"}county=${c.id}">${esc(c.name)}</a>`).join("")}</div>`;
}

export async function pricesView(main, _params, query) {
  document.title = `${t("nav_prices")} · ShambaSense`;
  const county = query.get("county") || (store.user && store.user.county) || "";
  main.innerHTML = `<h1 class="page-title">${esc(t("nav_prices"))}</h1><p class="hint">${esc(t("prices_hint"))}</p>
    ${countyChips(county, "#/prices")}<div id="list">${loading(t("loading_prices"))}</div>`;
  try {
    const rows = await api(`/api/prices/summary?${qs({ county })}`);
    const src = [...new Set(rows.map((r) => r.source).filter(Boolean))].join(", ");
    $("#list", main).innerHTML = rows.length ? `<ul class="rows">${rows.map((r) => `
      <li><a class="row" href="#/prices/${r.crop}${county ? `?county=${county}` : ""}">
        <div><div class="row-title">${esc(r.name[store.lang] || r.name.en)}</div>
          <div class="row-sub">${esc(monthYear(r.latest_month + "-01"))}${r.scope === "national" && county ? ` · ${esc(t("national_fallback"))}` : ""}</div></div>
        <div class="row-end" style="display:flex;align-items:center;gap:0.75rem">${sparkline(r.spark)}
          <div><div class="big">KES ${num(r.latest_kes_kg)}<span class="small muted">/kg</span></div>
          ${r.change_12m_pct != null ? `<div class="small ${r.change_12m_pct >= 0 ? "up" : "down"}">${pct(r.change_12m_pct)} ${esc(t("vs_last_year"))}</div>` : ""}</div>
          ${icon("chev", "chev")}</div></a></li>`).join("")}</ul>
      <p class="small muted">${esc(t("source"))}: ${esc(src)}</p>` : `<div class="empty">${esc(t("no_prices"))}</div>`;
  } catch (err) { $("#list", main).innerHTML = `<p class="error">${esc(err.message)}</p>`; }
}

export async function priceDetail(main, [crop], query) {
  const county = query.get("county") || "";
  const name = store.cropName(crop);
  document.title = `${name} · ${t("nav_prices")} · ShambaSense`;
  main.innerHTML = `<a class="link-btn" href="#/prices${county ? `?county=${county}` : ""}">${esc(t("back_prices"))}</a>
    <h1 class="page-title">${esc(name)}</h1>${countyChips(county, `#/prices/${crop}`)}<div id="detail">${loading(t("loading_prices"))}</div>`;
  try {
    const s = await api(`/api/prices?${qs({ crop, county, months: 36 })}`);
    if (!s.points.length) { $("#detail", main).innerHTML = `<div class="empty">${esc(t("no_prices"))}</div>`; return; }
    const vals = s.points.slice(-12).map((p) => p.kes_kg);
    const where = s.scope === "county" ? store.county(county).name : t("all_kenya");
    $("#detail", main).innerHTML = `
      <dl class="stat-row">
        <div class="stat"><dt>${esc(t("latest_price"))}</dt><dd>KES ${num(s.latest_kes_kg)}<small>/kg</small></dd></div>
        <div class="stat"><dt>${esc(t("change_12m"))}</dt><dd class="${(s.change_12m_pct || 0) >= 0 ? "up" : "down"}">${s.change_12m_pct != null ? pct(s.change_12m_pct) : "–"}</dd></div>
        <div class="stat"><dt>${esc(t("range_12m"))}</dt><dd>${num(Math.min(...vals))}–${num(Math.max(...vals))}<small> KES/kg</small></dd></div>
      </dl>
      <figure style="margin:0 0 1rem"><figcaption class="small muted" style="margin-bottom:0.5rem">${esc(t("price_chart_caption", where))}</figcaption>
        <div id="chart"></div></figure>
      <p class="small muted">${esc(t("markets"))}: ${esc(s.markets.join(", ") || "–")}. ${esc(t("source"))}: ${esc(s.source)}${s.scope === "national" && county ? `. ${esc(t("national_fallback"))}` : ""}.</p>`;
    const holder = $("#chart", main);
    holder.innerHTML = priceChart(s.points, holder.clientWidth || 700, t("price_chart_caption", where));
  } catch (err) { $("#detail", main).innerHTML = `<p class="error">${esc(err.message)}</p>`; }
}
