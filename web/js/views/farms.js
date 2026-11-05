// My farms: list, add (map or county), and each farm's advice, reminders and actions.
import { api, qs } from "../api.js";
import { t } from "../i18n.js";
import { createMap, inKenya, locate, nearestCounty } from "../map.js";
import { renderResult } from "../results.js";
import { store } from "../store.js";
import { $, dayMonth, esc, icon, loading, toast } from "../ui.js";

function signedOut(main) {
  main.innerHTML = `<h1 class="page-title">${esc(t("nav_farms"))}</h1>
    <div class="empty"><strong>${esc(t("farms_signin_title"))}</strong>${esc(t("farms_signin"))}
    <p><a class="btn btn-primary" href="#/me">${esc(t("signin_or_register"))}</a></p></div>`;
}

export async function farmsList(main) {
  document.title = `${t("nav_farms")} · ShambaSense`;
  if (!store.user) return signedOut(main);
  main.innerHTML = `<h1 class="page-title">${esc(t("nav_farms"))}</h1>${loading(t("loading_farms"))}`;
  const [farms, reminders] = await Promise.all([api("/api/farms"), api("/api/reminders").catch(() => [])]);
  const next = (id) => reminders.find((r) => r.farm_id === id && r.status === "scheduled");
  main.innerHTML = `
    <div class="farm-head"><div><h1 class="page-title">${esc(t("nav_farms"))}</h1>
      <p class="hint">${esc(t("farms_hint"))}</p></div>
      <a class="btn btn-primary" href="#/farms/new">${icon("plus")}${esc(t("add_farm"))}</a></div>
    ${farms.length ? `<ul class="rows">${farms.map((f) => {
      const rem = next(f.id);
      return `<li><a class="row" href="#/farms/${f.id}"><div><div class="row-title">${esc(f.name)}</div>
        <div class="row-sub">${esc(f.county_name)}${f.area_acres ? ` · ${esc(t("acres", f.area_acres))}` : ""}${f.lat != null ? ` · ${esc(t("on_map"))}` : ""}</div>
        ${rem ? `<span class="pill pill-ok">${icon("bell")} ${esc(t("reminder_on", dayMonth(rem.send_on)))}</span>` : ""}</div>
        ${icon("chev", "chev")}</a></li>`;
    }).join("")}</ul>` : `<div class="empty"><strong>${esc(t("no_farms_title"))}</strong>${esc(t("no_farms"))}</div>`}`;
}

export async function farmNew(main) {
  document.title = `${t("add_farm")} · ShambaSense`;
  if (!store.user) return signedOut(main);
  main.innerHTML = `
    <a class="link-btn" href="#/farms">${esc(t("back_farms"))}</a>
    <h1 class="page-title">${esc(t("add_farm"))}</h1>
    <p class="hint">${esc(t("add_farm_hint"))}</p>
    <form class="form" id="farm-form" novalidate>
      <div class="field"><label for="f-name">${esc(t("farm_name"))}</label>
        <input class="input" id="f-name" required maxlength="80" placeholder="${esc(t("farm_name_ph"))}" autocomplete="off"></div>
      <span class="label">${esc(t("farm_where"))}</span>
      <div class="map" id="map" style="margin:0.4rem 0 0.6rem"></div>
      <div class="place-row"><button type="button" class="chip" id="locate">${icon("locate")}${esc(t("use_location"))}</button></div>
      <div class="field"><label for="f-county">${esc(t("or_county"))}</label>
        <select class="select" id="f-county"><option value="">${esc(t("choose_county"))}</option>
        ${store.counties.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></div>
      <p class="picked" id="picked"></p>
      <div class="field"><label for="f-area">${esc(t("farm_area"))}</label>
        <input class="input" id="f-area" type="number" min="0.1" step="0.1" inputmode="decimal"></div>
      <button class="btn btn-primary btn-big" type="submit">${esc(t("save_farm"))}</button>
      <p class="error" id="error" role="alert" hidden></p>
    </form>`;
  let point = null;
  const map = createMap($("#map", main), { counties: store.counties, missingText: t("map_missing"),
    onPick: (lat, lon) => setPoint(lat, lon), onCounty: (id) => { $("#f-county", main).value = id; point = null; show(); } });
  function setPoint(lat, lon) {
    if (!inKenya(lat, lon)) { toast(t("outside_kenya")); return; }
    point = { lat, lon };
    $("#f-county", main).value = nearestCounty(store.counties, lat, lon).county.id;
    map.setMarker(lat, lon);
    show();
  }
  function show() {
    const c = store.county($("#f-county", main).value);
    $("#picked", main).textContent = point && c ? t("picked_point", point.lat.toFixed(3), point.lon.toFixed(3), c.name) : c ? t("picked_county", c.name) : "";
  }
  $("#f-county", main).addEventListener("change", () => { point = null; show(); });
  $("#locate", main).addEventListener("click", async () => {
    try { const p = await locate(); setPoint(p.lat, p.lon); map.flyTo(p.lat, p.lon, 12); } catch { toast(t("locate_failed")); }
  });
  map.invalidate();
  $("#farm-form", main).addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#error", main);
    const body = { name: $("#f-name", main).value.trim(), county: $("#f-county", main).value || null };
    const area = parseFloat($("#f-area", main).value);
    if (area > 0) body.area_acres = area;
    if (point) Object.assign(body, point);
    if (!body.name) { err.textContent = t("farm_name_required"); err.hidden = false; return; }
    if (!body.county && !point) { err.textContent = t("farm_place_required"); err.hidden = false; return; }
    try {
      const f = await api("/api/farms", { method: "POST", body });
      toast(t("farm_saved", f.name));
      location.hash = `#/farms/${f.id}`;
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  });
}

export async function farmDetail(main, [id], query) {
  if (!store.user) return signedOut(main);
  main.innerHTML = loading(t("loading"));
  const farms = await api("/api/farms");
  const farm = farms.find((f) => String(f.id) === id);
  if (!farm) { main.innerHTML = `<p class="error">${esc(t("farm_missing"))}</p><a href="#/farms">${esc(t("back_farms"))}</a>`; return; }
  document.title = `${farm.name} · ShambaSense`;
  const county = store.county(farm.county);
  let season = query.get("season") && farm.seasons.includes(query.get("season")) ? query.get("season") : county.default_season;
  main.innerHTML = `
    <a class="link-btn" href="#/farms">${esc(t("back_farms"))}</a>
    <div class="farm-head"><div><h1 class="page-title">${esc(farm.name)}</h1>
      <p class="hint">${esc(farm.county_name)}${farm.area_acres ? ` · ${esc(t("acres", farm.area_acres))}` : ""}</p></div>
      <div class="chips"><a class="chip" href="#/weather?farm=${farm.id}">${icon("rain")}${esc(t("nav_weather"))}</a>
      <button type="button" class="chip" id="delete">${icon("trash")}${esc(t("delete_farm"))}</button></div></div>
    <div class="segmented" id="seasons" role="group" style="max-width:440px;margin-bottom:1.5rem">
      ${farm.seasons.map((s) => `<button type="button" data-s="${s}" aria-pressed="${s === season}">${esc(t(s))}</button>`).join("")}</div>
    <section id="answer" aria-live="polite" aria-busy="true">${loading(t("loading"))}</section>`;
  const answer = $("#answer", main);
  async function load() {
    answer.setAttribute("aria-busy", "true");
    try {
      const r = await api(`/api/farms/${farm.id}/advice?${qs({ season, lang: store.lang })}`);
      renderResult(answer, r, { farm });
    } catch (err) { answer.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    answer.setAttribute("aria-busy", "false");
  }
  $("#seasons", main).addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    season = b.dataset.s;
    main.querySelectorAll("#seasons button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    load();
  });
  $("#delete", main).addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    if (btn.dataset.confirm !== "1") { btn.dataset.confirm = "1"; btn.lastChild.textContent = t("delete_confirm"); return; }
    try { await api(`/api/farms/${farm.id}`, { method: "DELETE" }); toast(t("farm_deleted")); location.hash = "#/farms"; }
    catch (err) { toast(err.message); }
  });
  load();
}
