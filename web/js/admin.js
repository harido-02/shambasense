// Admin dashboard: usage, model and retraining, KMD outlooks, reminders and SMS, feedback, users.
import { api } from "./api.js";
import { usageChart } from "./charts.js";
import { store } from "./store.js";
import { $, esc, num, toast } from "./ui.js";

store.lang = "en";   // the dashboard is for staff and is in English
const main = $("#main");
const CHANNEL_COLORS = { app: "#1F5E3B", web: "#7FB08F", ussd: "#F2C230", api: "#9A9187" };
const CHANNEL_NAMES = { app: "App (signed in)", web: "Web", ussd: "USSD", api: "API" };
let counties = [];
let crops = [];

function signInForm(message = "") {
  $("#signout").hidden = true;
  main.innerHTML = `<h1 class="page-title">Administrator sign-in</h1>
    <p class="hint">Use the phone number and PIN of an administrator account. To create one on Windows, double-click
    <strong>make_admin.bat</strong> in the ShambaSense folder; elsewhere run
    <code>python -m shambasense.cli create-admin --phone 07XXXXXXXX --pin XXXX</code>. On the hosted copy, set
    <code>ADMIN_PHONE</code> and <code>ADMIN_PIN</code>.</p>
    <form class="form" id="login">
      <div class="field"><label for="phone">Mobile number</label><input class="input" id="phone" type="tel" autocomplete="tel" required></div>
      <div class="field"><label for="pin">PIN</label><input class="input input-pin" id="pin" type="password" inputmode="numeric" maxlength="4" autocomplete="current-password" required></div>
      <button class="btn btn-primary btn-big" type="submit">Sign in</button>
      <p class="error" id="err" role="alert" ${message ? "" : "hidden"}>${esc(message)}</p>
    </form>`;
  $("#login").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/auth/login", { method: "POST", auth: false, body: { phone: $("#phone").value, pin: $("#pin").value } });
      if (!res.user.is_admin) { signInForm("This account is not an administrator."); return; }
      store.signIn(res.token, res.user);
      dashboard();
    } catch (err) { $("#err").textContent = err.message; $("#err").hidden = false; }
  });
}

const stat = (label, value, small = "") => `<div class="stat"><dt>${esc(label)}</dt><dd>${value}${small ? `<small> ${esc(small)}</small>` : ""}</dd></div>`;
const bars = (obj, names = {}) => {
  const entries = Object.entries(obj || {});
  if (!entries.length) return `<p class="muted">No data yet.</p>`;
  const max = Math.max(...entries.map(([, v]) => v));
  return `<ul class="bars">${entries.map(([k, v]) => `<li><span>${esc(names[k] || k)}</span>
    <span class="bar" style="width:${Math.max(2, (v / max) * 100)}%"></span><span class="n">${num(v)}</span></li>`).join("")}</ul>`;
};
const table = (rows, cols) => rows.length ? `<div class="table-wrap"><table class="data"><thead><tr>${cols.map(([, label, cls]) =>
  `<th class="${cls || ""}">${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${cols.map(([key, , cls, fmt]) =>
  `<td class="${cls || ""}">${esc(fmt ? fmt(r[key], r) : r[key] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<p class="muted">Nothing yet.</p>`;
const when = (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "");

async function dashboard() {
  $("#signout").hidden = false;
  main.innerHTML = `<p class="loading">Loading the dashboard…</p>`;
  let stats, feedback, sms, users, outlooks;
  try {
    [stats, feedback, sms, users, outlooks, counties, crops] = await Promise.all([
      api("/api/admin/stats"), api("/api/admin/feedback"), api("/api/admin/sms"), api("/api/admin/users"),
      api("/api/admin/outlooks"), api("/api/counties", { auth: false }), api("/api/crops", { auth: false })]);
  } catch (err) {
    if (err.status === 401 || err.status === 403) { store.signOutLocal(); signInForm(err.message); return; }
    main.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    return;
  }
  const countyName = (id) => (counties.find((c) => c.id === id) || {}).name || id || "";
  const cropName = (id) => ((crops.find((c) => c.id === id) || {}).name || {}).en || id || "";
  const m = stats.model;
  const smsSent = (stats.sms.sent || 0), smsLogged = Object.values(stats.sms).reduce((a, b) => a + b, 0);
  main.innerHTML = `
    <h1 class="page-title">Dashboard</h1>
    ${m.data_quality === "synthetic" ? `<p class="note"><strong>The model is trained on synthetic test data.</strong> Load KilimoSTAT yields and retrain before real use.</p>` : ""}
    <dl class="stat-row">
      ${stat("Farmers with accounts", num(stats.users))}
      ${stat("Saved farms", num(stats.farms))}
      ${stat("Advice given", num(stats.recommendations), "all time")}
      ${stats.feedback.avg_rating != null ? stat("Average feedback", stats.feedback.avg_rating, `of 5 · ${stats.feedback.count} replies`) : stat("Average feedback", "None yet")}
      ${stat("SMS sent", num(smsSent), `${smsLogged} logged`)}
    </dl>
    <h2 class="section-title">Advice given per day, last 30 days</h2>
    <div id="usage"></div>
    <div class="key">${Object.entries(CHANNEL_COLORS).map(([k, c]) => `<span style="display:inline-flex;align-items:center;gap:0.35rem"><i style="width:12px;height:12px;border-radius:2px;background:${c};display:inline-block"></i>${CHANNEL_NAMES[k]}</span>`).join("")}</div>

    <div class="admin-grid">
      <section><h2 class="section-title">Top recommended crops</h2>${bars(Object.fromEntries(Object.entries(stats.top_crops).map(([k, v]) => [cropName(k), v])))}</section>
      <section><h2 class="section-title">Advice by county</h2>${bars(Object.fromEntries(Object.entries(stats.by_county).map(([k, v]) => [countyName(k), v])))}</section>

      <section><h2 class="section-title">Yield model</h2>
        <dl class="stat-row">
          ${stat("Training data", esc(m.data_quality || "none"))}
          ${stat("Training rows", m.rows ?? "–")}
          ${stat("Error, unseen years", m.mae_year != null ? m.mae_year.toFixed(2) : "–", "t/ha")}
          ${stat("Error, unseen years", m.mape_year != null ? m.mape_year.toFixed(1) + "%" : "–", "MAPE")}
        </dl>
        <p class="muted small">Trained ${esc(when(m.trained_at) || "never")}. Retraining rebuilds the training table from the database, runs cross-validation and replaces the model; the app picks it up automatically.</p>
        <button type="button" class="btn btn-primary" id="retrain">Retrain the model</button>
        <p class="small" id="retrain-status" aria-live="polite"></p>
      </section>

      <section><h2 class="section-title">Reminders and SMS</h2>
        <p class="${stats.sms_configured ? "" : "note"}">${stats.sms_configured ? "Africa's Talking is configured." :
          "<strong>SMS is not configured.</strong> Messages are logged but not sent. Set AT_USERNAME and AT_API_KEY to send them."}</p>
        ${bars(stats.reminders)}
        <p style="margin-top:1rem"><button type="button" class="btn" id="run-reminders">Send due reminders now</button></p>
        <form class="form" id="test-sms" style="margin-top:1rem">
          <div class="field"><label for="sms-phone">Send a test SMS to</label><input class="input" id="sms-phone" type="tel" placeholder="0712 345 678" required></div>
          <button class="btn btn-quiet" type="submit">Send test SMS</button></form>
      </section>

      <section><h2 class="section-title">Seasonal outlook (KMD)</h2>
        <p class="muted small">Enter the tercile probabilities from the latest KMD seasonal forecast. They weight past seasons when advice is given.</p>
        <form class="form" id="outlook">
          <div class="field"><label for="o-county">County</label><select class="select" id="o-county">${counties.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></div>
          <div class="field"><label for="o-season">Season</label><select class="select" id="o-season"><option value="long_rains">Long rains</option><option value="short_rains">Short rains</option></select></div>
          <div class="field"><label for="o-year">Year</label><input class="input" id="o-year" type="number" value="${new Date().getFullYear() + 1}" min="2024" max="2100"></div>
          <div class="field"><label>Chance of below / near / above normal rain (%)</label>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem">
              <input class="input" id="o-below" type="number" min="0" max="100" value="33" aria-label="Below normal %">
              <input class="input" id="o-normal" type="number" min="0" max="100" value="34" aria-label="Near normal %">
              <input class="input" id="o-above" type="number" min="0" max="100" value="33" aria-label="Above normal %"></div></div>
          <div class="field"><label for="o-source">Source</label><input class="input" id="o-source" value="KMD seasonal outlook"></div>
          <button class="btn btn-primary" type="submit">Save outlook</button>
        </form>
        <div style="margin-top:1rem">${table(outlooks, [["county_id", "County", "", countyName], ["season", "Season", "", (v) => v.replace("_", " ")], ["year", "Year"],
          ["p_below", "Below", "num", (v) => Math.round(v * 100) + "%"], ["p_normal", "Normal", "num", (v) => Math.round(v * 100) + "%"],
          ["p_above", "Above", "num", (v) => Math.round(v * 100) + "%"], ["source", "Source"]])}</div>
      </section>
    </div>

    <h2 class="section-title">Farmer feedback</h2>
    ${table(feedback, [["created_at", "When", "", when], ["user_name", "Farmer"], ["county_id", "County", "", countyName], ["season", "Season", "", (v) => (v || "").replace("_", " ")],
      ["year", "Year"], ["crop", "Crop planted", "", cropName], ["rating", "Rating", "num"], ["yield_bags_acre", "Bags/acre", "num"], ["notes", "Notes"]])}
    <h2 class="section-title">SMS log</h2>
    ${table(sms, [["created_at", "When", "", when], ["to_phone", "To"], ["status", "Status"], ["message", "Message"]])}
    <h2 class="section-title">Accounts</h2>
    ${table(users, [["created_at", "Joined", "", when], ["name", "Name"], ["phone", "Phone"], ["county_id", "County", "", countyName], ["lang", "Language"],
      ["farms", "Farms", "num"], ["sms_opt_in", "SMS", "", (v) => (v ? "yes" : "no")], ["is_admin", "Admin", "", (v) => (v ? "yes" : "")]])}`;

  const usage = $("#usage");
  usage.innerHTML = usageChart(stats.daily, usage.clientWidth || 900, CHANNEL_COLORS);

  $("#retrain").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try { await api("/api/admin/retrain", { method: "POST" }); pollRetrain(); } catch (err) { toast(err.message); e.currentTarget.disabled = false; }
  });
  $("#run-reminders").addEventListener("click", async () => {
    try { const r = await api("/api/admin/reminders/run", { method: "POST" }); toast(`Sent ${r.sent || 0}, failed ${r.failed || 0}, not configured ${r.not_configured || 0}.`); }
    catch (err) { toast(err.message); }
  });
  $("#test-sms").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const r = await api("/api/admin/sms/test", { method: "POST", body: { phone: $("#sms-phone").value } }); toast(`Test SMS: ${r.status.replace("_", " ")}.`); }
    catch (err) { toast(err.message); }
  });
  $("#outlook").addEventListener("submit", async (e) => {
    e.preventDefault();
    const p = ["below", "normal", "above"].map((k) => Number($(`#o-${k}`).value) / 100);
    if (Math.abs(p[0] + p[1] + p[2] - 1) > 0.02) { toast("The three chances must add up to 100%."); return; }
    try {
      await api("/api/admin/outlook", { method: "POST", body: { county: $("#o-county").value, season: $("#o-season").value,
        year: Number($("#o-year").value), p_below: p[0], p_normal: p[1], p_above: p[2], source: $("#o-source").value } });
      toast("Outlook saved."); dashboard();
    } catch (err) { toast(err.message); }
  });
  api("/api/admin/retrain").then((s) => { if (s.running) pollRetrain(); else showRetrain(s); }).catch(() => {});
}

function showRetrain(s) {
  const el = $("#retrain-status");
  if (!el) return;
  if (s.running) el.textContent = `Retraining since ${when(s.started_at)}… this takes a few minutes.`;
  else if (s.error) el.innerHTML = `<span class="error">Last retraining failed: ${esc(s.error)}</span>`;
  else if (s.result) el.textContent = `Last retraining finished ${when(s.finished_at)}: ${s.result.rows} rows, error ${s.result.mae_t_ha?.toFixed(2)} t/ha (${s.result.data_quality} data).`;
  $("#retrain").disabled = Boolean(s.running);
}

async function pollRetrain() {
  const s = await api("/api/admin/retrain").catch(() => null);
  if (!s) return;
  showRetrain(s);
  if (s.running) setTimeout(pollRetrain, 4000);
  else if (s.result) { toast("Model retrained."); }
}

$("#signout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  store.signOutLocal();
  signInForm();
});

if (store.token && store.user && store.user.is_admin) dashboard();
else signInForm();
