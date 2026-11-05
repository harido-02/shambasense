// Small helpers shared by every screen: escaping, formatting, icons, toasts.
import { store } from "./store.js";

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const MONTHS = {
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  sw: ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ago", "Sep", "Okt", "Nov", "Des"],
};
const WEEKDAYS = {
  en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  sw: ["Jpl", "Jtt", "Jnn", "Jtn", "Alh", "Iju", "Jms"],
};
export const months = () => MONTHS[store.lang] || MONTHS.en;
export const parseDate = (s) => { const [y, m, d] = String(s).slice(0, 10).split("-").map(Number); return new Date(Date.UTC(y, m - 1, d || 1)); };
export const dayMonth = (s) => { const d = parseDate(s); return `${d.getUTCDate()} ${months()[d.getUTCMonth()]}`; };
export const weekday = (s) => (WEEKDAYS[store.lang] || WEEKDAYS.en)[parseDate(s).getUTCDay()];
export const monthYear = (s) => { const d = parseDate(s); return `${months()[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };

const NUM = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });
export const num = (v) => NUM.format(v);
export const one = (v) => (Math.abs(v) >= 10 ? num(v) : Number(v).toFixed(1));
// Money rounded to the precision the model can honestly offer.
export const nice = (v) => (Math.abs(v) < 10000 ? Math.round(v / 100) * 100 : Math.round(v / 1000) * 1000);
export const kes = (v) => (nice(v) < 0 ? "−KES " : "KES ") + num(Math.abs(nice(v)));
export const pct = (v) => `${v > 0 ? "+" : ""}${Number(v).toFixed(0)}%`;

const PATHS = {
  sprout: '<path d="M12 21v-9"/><path d="M12 12c0-4-3-6-7-6 0 4 3 6 7 6z"/><path d="M12 10c0-4 3-6.5 7-6.5 0 4-3 6.5-7 6.5z"/><path d="M6 21h12"/>',
  farm: '<path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8L3 12z"/><circle cx="7.5" cy="8.5" r="1.5"/>',
  rain: '<path d="M7 15a4 4 0 0 1-.6-8 5.5 5.5 0 0 1 10.6 1.5A3.5 3.5 0 0 1 17 15H7z"/><path d="M8 18l-1 2M12 18l-1 2M16 18l-1 2"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5"/>',
  chev: '<path d="M9 5l7 7-7 7"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  locate: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  bell: '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4l2-2z"/><path d="M10 21h4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14"/>',
  install: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v3h16v-3"/>',
  save: '<path d="M6 3h12v18l-6-4-6 4V3z"/>',
};
export function icon(name, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name] || ""}</svg>`;
}

let toastTimer;
export function hideToast() { const el = $("#toast"); if (el) el.hidden = true; }

export function toast(message) {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    el.setAttribute("role", "status");
    document.body.append(el);
  }
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

export const loading = (text) => `<p class="loading">${esc(text)}</p>`;

export function seasonLabel(season, t) { return t(season); }
