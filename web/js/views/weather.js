// Weather: 14-day rain and temperature forecast for a saved farm, a county or the current location.
import { api, qs } from "../api.js";
import { rainChart } from "../charts.js";
import { t } from "../i18n.js";
import { inKenya, locate } from "../map.js";
import { store } from "../store.js";
import { $, dayMonth, esc, icon, loading, toast, weekday } from "../ui.js";

export async function weatherView(main, _params, query) {
  document.title = `${t("nav_weather")} · ShambaSense`;
  const farms = store.user ? await api("/api/farms").catch(() => []) : [];
  let target = null;
  if (query.get("farm")) { const f = farms.find((x) => String(x.id) === query.get("farm")); if (f) target = { farm: f }; }
  if (!target && query.get("county")) target = { county: query.get("county") };
  if (!target && farms.length) target = { farm: farms[0] };
  if (!target) target = { county: (store.place && store.place.county) || (store.user && store.user.county) || store.counties[0].id };

  const active = (k, v) => (target[k] && (target[k].id || target[k]) === v ? "active" : "");
  main.innerHTML = `<h1 class="page-title">${esc(t("nav_weather"))}</h1><p class="hint">${esc(t("weather_hint"))}</p>
    <div class="chips" style="margin-bottom:1.25rem">
      <button type="button" class="chip" id="locate">${icon("locate")}${esc(t("use_location"))}</button>
      ${farms.map((f) => `<a class="chip ${active("farm", f.id)}" href="#/weather?farm=${f.id}">${icon("farm")}${esc(f.name)}</a>`).join("")}
      ${store.counties.map((c) => `<a class="chip ${active("county", c.id)}" href="#/weather?county=${c.id}">${esc(c.name)}</a>`).join("")}
    </div><div id="wx">${loading(t("loading_weather"))}</div>`;

  $("#locate", main).addEventListener("click", async () => {
    try {
      const p = await locate();
      if (!inKenya(p.lat, p.lon)) { toast(t("outside_kenya")); return; }
      show({ lat: p.lat, lon: p.lon }, t("your_location"));
    } catch { toast(t("locate_failed")); }
  });

  async function show(params, label) {
    const box = $("#wx", main);
    box.innerHTML = loading(t("loading_weather"));
    try {
      const w = await api(`/api/weather?${qs({ ...params, lang: store.lang })}`);
      box.innerHTML = `<h2 class="section-title" style="margin-top:0">${esc(t("forecast_for", label))}</h2>
        ${w.cachedAt ? `<ul class="warning-list"><li>${esc(t("cached_result", w.cachedAt))}</li></ul>` : ""}
        <p class="lede" style="margin-top:0">${w.summary.map(esc).join(" ")}</p>
        <figure style="margin:0 0 1.25rem"><div id="chart"></div>
          <figcaption class="key"><span class="key-rain">${esc(t("rain_mm"))}</span><span class="key-temp">${esc(t("temp_max"))}</span><span class="key-tmin">${esc(t("temp_min"))}</span></figcaption></figure>
        <div class="days" role="list">${w.days.map((d) => `<div class="day ${(d.rain_mm || 0) >= 5 ? "wet" : ""}" role="listitem">
          <div class="d">${esc(weekday(d.date))} ${esc(dayMonth(d.date))}</div>
          <div class="r">${d.rain_mm != null ? Math.round(d.rain_mm) : "–"} mm</div>
          <div class="t">${d.rain_prob != null ? d.rain_prob + "%" : ""}</div>
          <div class="t">${d.tmin_c != null ? Math.round(d.tmin_c) : "–"}–${d.tmax_c != null ? Math.round(d.tmax_c) : "–"}°C</div></div>`).join("")}</div>
        <p class="small muted" style="margin-top:1rem">${esc(w.source)}</p>`;
      const holder = $("#chart", main);
      holder.innerHTML = rainChart(w.days, holder.clientWidth || 700, t("forecast_for", label), weekday, { rain: t("chart_rain"), temp: t("chart_temp") });
    } catch (err) { box.innerHTML = `<div class="empty"><strong>${esc(t("weather_unavailable"))}</strong>${esc(err.message)}</div>`; }
  }

  if (target.farm) {
    const f = target.farm;
    const c = store.county(f.county);
    show(f.lat != null ? { lat: f.lat, lon: f.lon } : { county: f.county }, f.lat != null ? f.name : `${f.name} (${c.name})`);
  } else {
    show({ county: target.county }, store.county(target.county).name);
  }
}
