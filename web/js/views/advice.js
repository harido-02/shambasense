// Advice: pick a place (map, my location, county or saved farm) and a season, get ranked crops.
import { api, qs } from "../api.js";
import { t } from "../i18n.js";
import { createMap, inKenya, locate, nearestCounty } from "../map.js";
import { renderResult } from "../results.js";
import { store } from "../store.js";
import { $, $$, esc, icon, loading, toast } from "../ui.js";

const SEASON_MONTHS = { long_rains: "season_lr_months", short_rains: "season_sr_months" };

export async function adviceView(main) {
  document.title = "ShambaSense";
  const farms = store.user ? await api("/api/farms").catch(() => []) : [];
  main.innerHTML = `
    <div class="advice">
      <section class="ask" aria-labelledby="ask-title">
        <h1 id="ask-title" class="page-title">${esc(t("ask_title"))}</h1>
        <p class="hint">${esc(t("ask_hint"))}</p>
        <div class="map" id="map" aria-label="${esc(t("map_label"))}"></div>
        <div class="place-row">
          <button type="button" class="chip" id="locate">${icon("locate")}${esc(t("use_location"))}</button>
          ${farms.map((f) => `<a class="chip" href="#/farms/${f.id}">${icon("farm")}${esc(f.name)}</a>`).join("")}
        </div>
        <div class="chips" id="counties" role="group" aria-label="${esc(t("counties"))}">
          ${store.counties.map((c) => `<button type="button" class="chip" data-id="${c.id}" aria-pressed="false">${esc(c.name)}</button>`).join("")}
        </div>
        <p class="picked" id="picked" aria-live="polite"></p>
        <span class="label" id="season-label">${esc(t("season"))}</span>
        <div class="segmented" id="seasons" role="group" aria-labelledby="season-label"></div>
        <button type="button" class="btn btn-primary btn-big" id="go" disabled>${esc(t("go"))}</button>
        <p class="error" id="error" role="alert" hidden></p>
      </section>
      <section class="answer" id="answer" aria-live="polite" aria-busy="false">
        <div class="empty"><strong>${esc(t("empty_title"))}</strong>${esc(t("empty"))}</div>
      </section>
    </div>`;

  let place = store.place && store.county(store.place.county) ? { ...store.place } : null;
  let season = store.season;

  const map = createMap($("#map", main), {
    counties: store.counties, missingText: t("map_missing"),
    onPick: (lat, lon) => pickPoint(lat, lon),
    onCounty: (id) => pickCounty(id),
  });

  function pickPoint(lat, lon) {
    if (!inKenya(lat, lon)) { toast(t("outside_kenya")); return; }
    const { county } = nearestCounty(store.counties, lat, lon);
    place = { lat, lon, county: county.id };
    map.setMarker(lat, lon);
    update();
  }
  function pickCounty(id) {
    const c = store.county(id);
    place = { county: id };
    map.flyTo(c.lat, c.lon, 8);
    map.setMarker(c.lat, c.lon);
    update();
  }
  function update() {
    $$("#counties .chip", main).forEach((b) => b.setAttribute("aria-pressed", String(place && place.lat === undefined && b.dataset.id === place.county)));
    const c = place && store.county(place.county);
    $("#picked", main).textContent = !c ? "" : place.lat !== undefined
      ? t("picked_point", place.lat.toFixed(3), place.lon.toFixed(3), c.name) : t("picked_county", c.name);
    const seasons = c ? c.seasons : ["long_rains", "short_rains"];
    if (!seasons.includes(season)) season = c ? c.default_season : null;
    $("#seasons", main).innerHTML = seasons.map((s) => `<button type="button" data-s="${s}" aria-pressed="${s === season}">
      ${esc(t(s))}<small>${esc(t(SEASON_MONTHS[s]))}</small></button>`).join("");
    $("#go", main).disabled = !place || !season;
  }

  $("#counties", main).addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) pickCounty(b.dataset.id); });
  $("#seasons", main).addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { season = b.dataset.s; update(); } });
  $("#locate", main).addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const p = await locate();
      pickPoint(p.lat, p.lon);
      map.flyTo(p.lat, p.lon, 10);
    } catch { toast(t("locate_failed")); } finally { btn.disabled = false; }
  });
  $("#go", main).addEventListener("click", () => getAdvice());

  async function getAdvice() {
    if (!place || !season) return;
    store.set({ place, season });
    const answer = $("#answer", main);
    $("#error", main).hidden = true;
    answer.setAttribute("aria-busy", "true");
    if (!answer.querySelector(".result-body")) answer.innerHTML = loading(t("loading"));
    $("#go", main).disabled = true;
    const params = { season, lang: store.lang, channel: "app" };
    if (place.lat !== undefined) Object.assign(params, { lat: place.lat.toFixed(4), lon: place.lon.toFixed(4) });
    else params.county = place.county;
    try {
      const r = await api(`/api/recommend?${qs(params)}`);
      renderResult(answer, r, { onSaved: (f) => { location.hash = `#/farms/${f.id}`; } });
      if (window.innerWidth < 1100) answer.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    } catch (err) {
      $("#error", main).textContent = err.message;
      $("#error", main).hidden = false;
      if (!answer.querySelector(".result-body")) answer.innerHTML = `<div class="empty"><strong>${esc(t("empty_title"))}</strong>${esc(t("empty"))}</div>`;
    } finally {
      answer.setAttribute("aria-busy", "false");
      $("#go", main).disabled = false;
    }
  }

  if (place) {
    const c = store.county(place.county);
    if (place.lat !== undefined) { map.setMarker(place.lat, place.lon); map.flyTo(place.lat, place.lon, 9); }
    else { map.setMarker(c.lat, c.lon); map.flyTo(c.lat, c.lon, 8); }
  }
  update();
  map.invalidate();
  if (place && season) getAdvice();
}
