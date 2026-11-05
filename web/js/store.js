// App state: language, sign-in, reference data and the last place used. Persisted per device.
const KEY = "shambasense.v1";

function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}

const saved = load();
const browserLang = (navigator.language || "en").toLowerCase().startsWith("sw") ? "sw" : "en";

export const store = {
  lang: saved.lang || browserLang,
  token: saved.token || null,
  user: saved.user || null,
  place: saved.place || null,          // { county } or { lat, lon, county }
  season: saved.season || null,
  counties: [],
  crops: [],
  health: null,
  online: navigator.onLine,
  installPrompt: null,
  listeners: new Set(),

  save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({ lang: this.lang, token: this.token, user: this.user,
        place: this.place, season: this.season }));
    } catch { /* storage can be unavailable; the app still works for this visit */ }
  },
  set(patch) {
    Object.assign(this, patch);
    this.save();
    this.listeners.forEach((fn) => fn(patch));
  },
  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },
  signIn(token, user) { this.set({ token, user, lang: user.lang || this.lang }); },
  signOutLocal() { this.set({ token: null, user: null }); },
  county(id) { return this.counties.find((c) => c.id === id); },
  cropName(id) { const c = this.crops.find((x) => x.id === id); return c ? c.name[this.lang] || c.name.en : id; },
};
