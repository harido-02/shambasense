// Renders one piece of advice: answer, season calendar, ranked crops, outlook, actions, feedback.
import { api } from "./api.js";
import { HA_PER_ACRE } from "./config.js";
import { t } from "./i18n.js";
import { store } from "./store.js";
import { $, dayMonth, esc, icon, kes, months, one, parseDate, toast } from "./ui.js";

export function renderResult(root, r, { farm = null, onSaved = null } = {}) {
  const top = r.recommendations[0];
  const name = (n) => (/^Irish/.test(n) ? n : n.toLowerCase());
  const warnings = r.warnings.filter((w) => !/SYNTHETIC|BANDIA/.test(w));
  const signedIn = Boolean(store.user);
  root.innerHTML = `
    <div class="result-body">
      ${r.cachedAt ? `<ul class="warning-list"><li>${esc(t("cached_result", r.cachedAt))}</li></ul>` : ""}
      <h2 class="headline">${esc(top ? t("headline", name(top.name), r.season_name, r.year) : t("headline_none", r.season_name, r.year))}</h2>
      <p class="lede">${esc(farm ? farm.name + ", " + r.location.county_name : r.location.county_name)}. ${esc(r.planting_window.advice)}</p>
      ${warnings.length ? `<ul class="warning-list">${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
      <div class="result-actions" id="result-actions"></div>
      ${r.recommendations.length ? calendar(r) : ""}
      <h3 class="section-title">${esc(t("ranked"))}</h3>
      ${r.recommendations.length ? `<ol class="ranked">${r.recommendations.map(cropItem).join("")}</ol>` : `<p class="muted">${esc(t("none_fit"))}</p>`}
      ${r.not_suitable.length ? `<div class="unsuitable"><h3 class="section-title">${esc(t("unsuitable"))}</h3><ul>${r.not_suitable
        .map((n) => `<li><strong>${esc(n.name)}</strong>${n.reason ? ": " + esc(n.reason) : ""}</li>`).join("")}</ul></div>` : ""}
      ${outlook(r)}
      <details class="feedback">
        <summary>${esc(t("fb_title"))}</summary>
        <form id="fb-form" class="form">
          <div class="field"><label for="fb-crop">${esc(t("fb_crop"))}</label>
            <select class="select" id="fb-crop">${[...r.recommendations, ...r.not_suitable].map((c) => `<option value="${c.crop}">${esc(c.name)}</option>`).join("")}</select></div>
          <div class="field"><label for="fb-rating">${esc(t("fb_rating"))}</label>
            <select class="select" id="fb-rating"><option value="">–</option>${[5, 4, 3, 2, 1].map((n) => `<option>${n}</option>`).join("")}</select></div>
          <div class="field"><label for="fb-yield">${esc(t("fb_yield"))}</label>
            <input class="input" id="fb-yield" type="number" min="0" step="0.5" inputmode="decimal"></div>
          <button class="btn" type="submit">${esc(t("fb_send"))}</button>
        </form>
      </details>
      <p class="small muted">${esc(t("model_note", r.model.trained_at ? r.model.trained_at.slice(0, 10) : "—", r.model.data_quality, r.model.requirements_verified))}</p>
    </div>`;

  // Actions: save this place as a farm, or set a reminder for a saved farm.
  const actions = $("#result-actions", root);
  if (farm) {
    actions.innerHTML = `<button class="btn" id="remind">${icon("bell")}${esc(t("remind_me"))}</button>`;
    $("#remind", root).addEventListener("click", async (e) => {
      e.currentTarget.disabled = true;
      try {
        const rem = await api(`/api/farms/${farm.id}/reminders`, { method: "POST", body: { season: r.season, year: r.year } });
        toast(t("reminder_set", dayMonth(rem.send_on)));
      } catch (err) { toast(err.message); e.currentTarget.disabled = false; }
    });
  } else if (signedIn) {
    actions.innerHTML = `<button class="btn" id="save-farm">${icon("save")}${esc(t("save_farm"))}</button>
      <form id="save-form" class="form" hidden><div class="field"><label for="farm-name">${esc(t("farm_name"))}</label>
      <input class="input" id="farm-name" required maxlength="80" placeholder="${esc(t("farm_name_ph"))}"></div>
      <button class="btn btn-primary" type="submit">${esc(t("save"))}</button></form>`;
    $("#save-farm", root).addEventListener("click", () => { $("#save-form", root).hidden = false; $("#save-farm", root).hidden = true; $("#farm-name", root).focus(); });
    $("#save-form", root).addEventListener("submit", async (e) => {
      e.preventDefault();
      const loc = r.location;
      const body = { name: $("#farm-name", root).value, county: loc.county };
      if (loc.distance_km > 0) Object.assign(body, { lat: loc.lat, lon: loc.lon });
      try {
        const f = await api("/api/farms", { method: "POST", body });
        toast(t("farm_saved", f.name));
        $("#save-form", root).hidden = true;
        onSaved && onSaved(f);
      } catch (err) { toast(err.message); }
    });
  } else {
    actions.innerHTML = `<p class="small muted">${t("signin_to_save")}</p>`;
  }

  $("#fb-form", root).addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { county: r.location.county, season: r.season, year: r.year, crop: $("#fb-crop", root).value };
    const rating = parseInt($("#fb-rating", root).value, 10), y = parseFloat($("#fb-yield", root).value);
    if (rating) body.rating = rating;
    if (y >= 0) body.yield_bags_acre = y;
    if (farm) body.farm_id = farm.id;
    try { await api("/api/feedback", { method: "POST", body }); toast(t("fb_thanks")); e.target.closest("details").open = false; }
    catch (err) { toast(err.message); }
  });
  requestAnimationFrame(() => drawCalendar(root, r));
}

function cropItem(c) {
  const facts = [];
  if (c.yield_bags_acre) {
    const y = c.yield_bags_acre;
    facts.push(fact(t("f_yield"), t("f_yield_bags", one(y.p10), one(y.p90)), t("f_yield_small_bags", one(y.p50), y.bag_kg)));
  } else if (c.yield_t_ha) {
    const y = c.yield_t_ha, a = HA_PER_ACRE;
    facts.push(fact(t("f_yield"), t("f_yield_t", (y.p10 * a).toFixed(1), (y.p90 * a).toFixed(1)), t("f_yield_small_t", (y.p50 * a).toFixed(1))));
  }
  if (c.gross_margin_kes_acre) {
    const m = c.gross_margin_kes_acre;
    facts.push(fact(t("f_profit"), `${kes(m.p10)} ${t("to")} ${kes(m.p90)}`, t("f_profit_small", kes(m.p50))));
  }
  if (c.prob_loss !== undefined) {
    const p = Math.round(c.prob_loss * 100);
    facts.push(fact(t("f_risk"), `<span class="${p >= 30 ? "risk-high" : ""}">${p}%</span>`));
  }
  facts.push(fact(t("f_harvest"), dayMonth(c.harvest_from)));
  return `<li class="crop"><div class="crop-rank" aria-hidden="true">${c.rank}</div><div>
    <div class="crop-head"><h4 class="crop-name">${esc(c.name)}</h4><span class="tag tag-${c.tier}">${esc(c.label)}</span></div>
    <dl class="facts">${facts.join("")}</dl>
    <details class="why"><summary>${esc(t("why"))}</summary><ul>${c.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>
  </div></li>`;
}
const fact = (label, value, small) => `<div class="fact"><dt>${esc(label)}</dt><dd>${value}${small ? `<small>${esc(small)}</small>` : ""}</dd></div>`;

function outlook(r) {
  const f = r.forecast;
  const parts = [["below", f.p_below], ["normal", f.p_normal], ["above", f.p_above]];
  const source = /^climatology/.test(f.source) ? t("climatology_source") : f.source;
  return `<div class="outlook"><h3>${esc(t("outlook_title"))}</h3>
    <div class="odds" aria-hidden="true">${parts.map(([k, p]) => `<div class="${k}" style="width:${(p * 100).toFixed(1)}%"></div>`).join("")}</div>
    <ul class="odds-key">${parts.map(([k, p]) => `<li class="${k}">${esc(t(k))} <strong>${Math.round(p * 100)}%</strong></li>`).join("")}</ul>
    <p>${esc(t("outlook_source", source, r.analog_seasons))}</p></div>`;
}

const calendar = () => `<figure class="calendar"><figcaption>${esc(t("calendar_caption"))}</figcaption><div class="cal"></div>
  <div class="key"><span class="key-plant">${esc(t("key_plant"))}</span><span class="key-grow">${esc(t("key_grow"))}</span></div></figure>`;

function drawCalendar(root, r) {
  const holder = root.querySelector(".cal");
  if (!holder) return;
  const crops = r.recommendations, pw = r.planting_window;
  const W = Math.max(300, Math.round(holder.clientWidth || 700));
  const narrow = W < 560;
  const labelW = narrow ? 104 : 150, padR = narrow ? 52 : 92, rowH = 34, top = 30;
  const H = top + crops.length * rowH + 8;
  const plantMid = pw.median ? parseDate(pw.median) : null;
  const starts = crops.map((c) => plantMid || new Date(parseDate(c.harvest_from) - c.days_to_maturity * 864e5));
  const first = pw.early ? parseDate(pw.early) : new Date(Math.min(...starts));
  const last = new Date(Math.max(...crops.map((c) => parseDate(c.harvest_from))));
  const t0 = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1);
  const t1 = Date.UTC(last.getUTCFullYear(), last.getUTCMonth() + 1, 1);
  const x = (v) => labelW + ((v - t0) / (t1 - t0)) * (W - labelW - padR);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("calendar_caption"))}">`;
  for (let m = new Date(t0); m.getTime() < t1; m = new Date(Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1))) {
    const xm = x(m.getTime());
    svg += `<line class="cal-rule" x1="${xm}" x2="${xm}" y1="${top - 6}" y2="${H}"/><text class="cal-month" x="${xm + 4}" y="${top - 12}">${months()[m.getUTCMonth()]}</text>`;
  }
  crops.forEach((c, i) => {
    const y = top + i * rowH + 6, h = rowH - 14;
    const s = starts[i].getTime(), e = parseDate(c.harvest_from).getTime();
    svg += `<text class="cal-name" x="0" y="${y + h / 2 + 5}">${esc(c.name.length > 15 && narrow ? c.name.slice(0, 13) + "…" : c.name)}</text>`;
    svg += `<rect class="cal-grow cal-bar" style="animation-delay:${i * 60}ms" x="${x(s)}" y="${y}" width="${Math.max(2, x(e) - x(s))}" height="${h}" rx="4"/>`;
    if (pw.early && pw.late) {
      const a = x(parseDate(pw.early).getTime()), b = x(parseDate(pw.late).getTime());
      svg += `<rect class="cal-plant" x="${a}" y="${y}" width="${Math.max(3, b - a)}" height="${h}" rx="4"/>`;
    }
    svg += `<text class="cal-harvest" x="${x(e) + 6}" y="${y + h / 2 + 4}">${narrow ? "" : esc(t("harvest")) + " "}${dayMonth(c.harvest_from)}</text>`;
  });
  holder.innerHTML = svg + "</svg>";
}
