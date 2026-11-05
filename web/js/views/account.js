// Account: sign in or create an account (phone + PIN), then profile, reminders, history and settings.
import { api } from "../api.js";
import { API_BASE } from "../config.js";
import { t } from "../i18n.js";
import { renderResult } from "../results.js";
import { store } from "../store.js";
import { $, dayMonth, esc, icon, loading, toast } from "../ui.js";

const countyOptions = (selected) => `<option value="">${esc(t("choose_county"))}</option>` +
  store.counties.map((c) => `<option value="${c.id}" ${c.id === selected ? "selected" : ""}>${esc(c.name)}</option>`).join("");

export async function accountView(main, _params, query) {
  document.title = `${t("nav_me")} · ShambaSense`;
  if (!store.user) return authForms(main, query.get("tab") === "register" ? "register" : "signin");
  main.innerHTML = loading(t("loading"));
  let user;
  try { user = await api("/api/me"); store.set({ user }); } catch { if (!store.user) return authForms(main, "signin"); user = store.user; }
  const [reminders, history] = await Promise.all([api("/api/reminders").catch(() => []), api("/api/me/history").catch(() => [])]);
  const upcoming = reminders.filter((r) => r.status === "scheduled");
  main.innerHTML = `
    <h1 class="page-title">${esc(t("nav_me"))}</h1>
    <p class="profile-name">${esc(user.name || t("farmer"))}</p>
    <p class="muted" style="margin-top:0.2rem">${esc(user.phone_masked)}${user.county ? ` · ${esc(store.county(user.county).name)}` : ""}</p>
    <div class="chips" style="margin:1rem 0 0.5rem">
      ${store.installPrompt ? `<button type="button" class="chip" id="install">${icon("install")}${esc(t("install_app"))}</button>` : ""}
      ${user.is_admin ? `<a class="chip" href="${API_BASE}/admin" target="${API_BASE ? "_blank" : "_self"}" rel="noopener">${esc(t("admin_dashboard"))}</a>` : ""}
    </div>

    <h2 class="section-title">${esc(t("reminders"))}</h2>
    ${upcoming.length ? `<ul class="rows">${upcoming.map((r) => `<li class="row"><div>
        <div class="row-title">${esc(r.farm_name)} · ${esc(t(r.season))} ${r.year}</div>
        <div class="row-sub">${esc(t("sms_on", dayMonth(r.send_on)))}</div></div>
        <button type="button" class="btn btn-quiet" data-cancel="${r.id}">${esc(t("cancel"))}</button></li>`).join("")}</ul>`
      : `<p class="muted">${esc(t("no_reminders"))}</p>`}

    <h2 class="section-title">${esc(t("history"))}</h2>
    ${history.length ? `<ul class="rows">${history.slice(0, 12).map((h) => `<li><a class="row" href="#/me/history/${h.id}"><div>
        <div class="row-title">${esc(h.crop_name || "–")}</div>
        <div class="row-sub">${esc(h.farm_name || h.county_name)} · ${esc(t(h.season))} ${h.year} · ${esc(dayMonth(h.created_at))}</div></div>
        ${icon("chev", "chev")}</a></li>`).join("")}</ul>` : `<p class="muted">${esc(t("no_history"))}</p>`}

    <h2 class="section-title">${esc(t("settings"))}</h2>
    <form class="form" id="profile">
      <div class="field"><label for="p-name">${esc(t("your_name"))}</label><input class="input" id="p-name" maxlength="80" value="${esc(user.name || "")}"></div>
      <div class="field"><label for="p-county">${esc(t("your_county"))}</label><select class="select" id="p-county">${countyOptions(user.county)}</select></div>
      <div class="field"><label for="p-lang">${esc(t("language"))}</label><select class="select" id="p-lang">
        <option value="en" ${user.lang === "en" ? "selected" : ""}>English</option><option value="sw" ${user.lang === "sw" ? "selected" : ""}>Kiswahili</option></select></div>
      <label class="switch"><span>${esc(t("sms_opt_in"))}</span><input type="checkbox" id="p-sms" ${user.sms_opt_in ? "checked" : ""}></label>
      <button class="btn btn-primary" type="submit" style="margin-top:1rem">${esc(t("save_changes"))}</button>
    </form>

    <details class="feedback" style="margin-top:1.5rem"><summary>${esc(t("change_pin"))}</summary>
      <form class="form" id="pin-form">
        <div class="field"><label for="pin-old">${esc(t("current_pin"))}</label><input class="input input-pin" id="pin-old" type="password" inputmode="numeric" maxlength="4" autocomplete="current-password"></div>
        <div class="field"><label for="pin-new">${esc(t("new_pin"))}</label><input class="input input-pin" id="pin-new" type="password" inputmode="numeric" maxlength="4" autocomplete="new-password"></div>
        <button class="btn" type="submit">${esc(t("change_pin"))}</button></form></details>

    <p style="margin-top:2rem"><button type="button" class="btn btn-danger" id="signout">${esc(t("sign_out"))}</button></p>
    <p class="small muted">${esc(t("privacy_note"))}</p>`;

  main.querySelectorAll("[data-cancel]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/reminders/${b.dataset.cancel}`, { method: "DELETE" }); toast(t("reminder_cancelled")); accountView(main, [], query); }
    catch (err) { toast(err.message); }
  }));
  $("#profile", main).addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const u = await api("/api/me", { method: "PATCH", body: { name: $("#p-name", main).value, county: $("#p-county", main).value || null,
        lang: $("#p-lang", main).value, sms_opt_in: $("#p-sms", main).checked } });
      const langChanged = u.lang !== store.lang;
      store.set({ user: u, lang: u.lang });
      toast(t("saved"));
      if (langChanged) window.dispatchEvent(new Event("hashchange"));
    } catch (err) { toast(err.message); }
  });
  $("#pin-form", main).addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("/api/me/pin", { method: "POST", body: { old_pin: $("#pin-old", main).value, new_pin: $("#pin-new", main).value } }); toast(t("pin_changed")); e.target.reset(); }
    catch (err) { toast(err.message); }
  });
  $("#signout", main).addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    store.signOutLocal();
    location.hash = "#/";
  });
  const install = $("#install", main);
  if (install) install.addEventListener("click", async () => { store.installPrompt.prompt(); store.installPrompt = null; install.remove(); });
}

function authForms(main, tab) {
  main.innerHTML = `
    <h1 class="page-title">${esc(t("nav_me"))}</h1>
    <p class="hint">${esc(t("account_why"))}</p>
    <div class="tabs-inline" role="tablist">
      <button type="button" role="tab" aria-selected="${tab === "signin"}" data-tab="signin">${esc(t("sign_in"))}</button>
      <button type="button" role="tab" aria-selected="${tab === "register"}" data-tab="register">${esc(t("create_account"))}</button>
    </div>
    <form class="form" id="auth-form" novalidate>
      ${tab === "register" ? `<div class="field"><label for="a-name">${esc(t("your_name"))}</label><input class="input" id="a-name" maxlength="80" autocomplete="name"></div>` : ""}
      <div class="field"><label for="a-phone">${esc(t("phone"))}</label>
        <input class="input" id="a-phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="0712 345 678" required></div>
      <div class="field"><label for="a-pin">${esc(t(tab === "register" ? "choose_pin" : "pin"))}</label>
        <input class="input input-pin" id="a-pin" type="password" inputmode="numeric" maxlength="4" pattern="[0-9]{4}" autocomplete="${tab === "register" ? "new-password" : "current-password"}" required>
        ${tab === "register" ? `<span class="help">${esc(t("pin_help"))}</span>` : ""}</div>
      ${tab === "register" ? `
        <div class="field"><label for="a-pin2">${esc(t("confirm_pin"))}</label><input class="input input-pin" id="a-pin2" type="password" inputmode="numeric" maxlength="4" autocomplete="new-password"></div>
        <div class="field"><label for="a-county">${esc(t("your_county"))}</label><select class="select" id="a-county">${countyOptions(store.place && store.place.county)}</select></div>` : ""}
      <button class="btn btn-primary btn-big" type="submit">${esc(t(tab === "register" ? "create_account" : "sign_in"))}</button>
      <p class="error" id="auth-error" role="alert" hidden></p>
    </form>
    <p class="small muted" style="margin-top:1.5rem;max-width:60ch">${esc(t("privacy_note"))}</p>`;
  main.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => authForms(main, b.dataset.tab)));
  $("#auth-form", main).addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#auth-error", main);
    err.hidden = true;
    const phone = $("#a-phone", main).value, pin = $("#a-pin", main).value;
    if (!/^\d{4}$/.test(pin)) { err.textContent = t("pin_four"); err.hidden = false; return; }
    if (tab === "register" && pin !== $("#a-pin2", main).value) { err.textContent = t("pin_mismatch"); err.hidden = false; return; }
    const btn = e.submitter || $("button[type=submit]", main);
    btn.disabled = true;
    try {
      const res = tab === "register"
        ? await api("/api/auth/register", { method: "POST", auth: false, body: { phone, pin, name: $("#a-name", main).value || null,
          county: $("#a-county", main).value || null, lang: store.lang } })
        : await api("/api/auth/login", { method: "POST", auth: false, body: { phone, pin } });
      store.signIn(res.token, res.user);
      toast(t(tab === "register" ? "welcome_new" : "welcome_back", res.user.name || ""));
      location.hash = tab === "register" ? "#/farms/new" : "#/";
    } catch (ex) { err.textContent = ex.message; err.hidden = false; btn.disabled = false; }
  });
}

export async function historyItem(main, [id]) {
  if (!store.user) return authForms(main, "signin");
  main.innerHTML = `<a class="link-btn" href="#/me">${esc(t("back_account"))}</a><section id="answer">${loading(t("loading"))}</section>`;
  try { renderResult($("#answer", main), await api(`/api/me/history/${id}`)); }
  catch (err) { $("#answer", main).innerHTML = `<p class="error">${esc(err.message)}</p>`; }
}
