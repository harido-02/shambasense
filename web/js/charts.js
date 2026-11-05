// Hand-drawn SVG charts sized to their container so text stays legible on phones.
import { esc, months, parseDate, num } from "./ui.js";

export function sparkline(values, w = 96, h = 28) {
  if (!values || values.length < 2) return "";
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * (w - 4) + 2},${h - 3 - ((v - lo) / span) * (h - 6)}`);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="M${pts.join("L")}"/></svg>`;
}

/** Monthly price line with area, min/max labels and year ticks. points: [{month:'2024-01', kes_kg}] */
export function priceChart(points, width, label) {
  const W = Math.max(300, Math.round(width)), H = W < 500 ? 220 : 260;
  const L = 44, R = 16, T = 18, B = 28;
  const vals = points.map((p) => p.kes_kg);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.12 || hi * 0.1 || 1;
  const y0 = Math.max(0, lo - pad), y1 = hi + pad;
  const x = (i) => L + (i / Math.max(1, points.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const step = niceStep((y1 - y0) / 4);
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
  for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) {
    svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${num(v)}</text>`;
  }
  points.forEach((p, i) => {
    const d = parseDate(p.month);
    if (d.getUTCMonth() === 0) {
      svg += `<line class="grid" x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H - B}"/><text class="axis" x="${x(i)}" y="${H - 8}" text-anchor="middle">${d.getUTCFullYear()}</text>`;
    }
  });
  const line = points.map((p, i) => `${x(i)},${y(p.kes_kg)}`).join("L");
  svg += `<path class="area" d="M${x(0)},${H - B}L${line}L${x(points.length - 1)},${H - B}Z"/>`;
  svg += `<path class="line" d="M${line}"/>`;
  const last = points.length - 1;
  svg += `<circle class="dot" cx="${x(last)}" cy="${y(points[last].kes_kg)}" r="4"/>`;
  svg += `<text class="label" x="${x(last) - 6}" y="${y(points[last].kes_kg) - 10}" text-anchor="end">KES ${num(points[last].kes_kg)}</text>`;
  return svg + "</svg>";
}

/** Daily rain (main panel, labelled bars) over a small max/min temperature panel.
 *  days: [{date, rain_mm, tmax_c, tmin_c}] */
export function rainChart(days, width, label, weekdayFn, text = {}) {
  const W = Math.max(300, Math.round(width)), narrow = W < 520;
  const L = 34, R = 34, T = 22, rainH = 130, gap = 34, tempH = 54, B = 38;
  const H = T + rainH + gap + tempH + B;
  const n = days.length, bw = (W - L - R) / n;
  const cx = (i) => L + bw * i + bw / 2;
  const rains = days.map((d) => d.rain_mm || 0);
  const maxRain = Math.max(10, Math.ceil(Math.max(...rains) / 10) * 10);
  const yr = (v) => T + rainH - (v / maxRain) * rainH;
  const temps = days.flatMap((d) => [d.tmax_c, d.tmin_c]).filter((v) => v != null);
  const tLo = Math.floor(Math.min(...temps) - 1), tHi = Math.ceil(Math.max(...temps) + 1);
  const t0 = T + rainH + gap;
  const yt = (v) => t0 + (1 - (v - tLo) / (tHi - tLo)) * tempH;
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">`;
  svg += `<text class="panel" x="0" y="${T - 8}">${esc(text.rain || "Rain, mm per day")}</text>`;
  [0, maxRain / 2, maxRain].forEach((v) => {
    svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${yr(v)}" y2="${yr(v)}"/><text class="axis" x="${L - 6}" y="${yr(v) + 4}" text-anchor="end">${v}</text>`;
  });
  rains.forEach((r, i) => {
    if (r <= 0) return;
    const h = Math.max(1.5, T + rainH - yr(r));
    svg += `<rect class="rain" x="${cx(i) - bw * 0.32}" y="${T + rainH - h}" width="${bw * 0.64}" height="${h}" rx="2"/>`;
    if (r >= 1) svg += `<text class="rain-label" x="${cx(i)}" y="${T + rainH - h - 4}" text-anchor="middle">${Math.round(r)}</text>`;
  });
  svg += `<text class="panel" x="0" y="${t0 - 10}">${esc(text.temp || "Temperature, °C")}</text>`;
  const path = (key) => days.map((d, i) => (d[key] == null ? null : `${cx(i)},${yt(d[key])}`)).filter(Boolean).join("L");
  svg += `<path class="tmax" d="M${path("tmax_c")}"/><path class="tmin" d="M${path("tmin_c")}"/>`;
  const last = days[n - 1];
  if (last.tmax_c != null) svg += `<text class="axis" x="${cx(n - 1) + 6}" y="${yt(last.tmax_c) + 4}">${Math.round(last.tmax_c)}°</text>`;
  if (last.tmin_c != null) svg += `<text class="axis" x="${cx(n - 1) + 6}" y="${yt(last.tmin_c) + 4}">${Math.round(last.tmin_c)}°</text>`;
  if (days[0].tmax_c != null) svg += `<text class="axis" x="${L - 6}" y="${yt(days[0].tmax_c) + 4}" text-anchor="end">${Math.round(days[0].tmax_c)}°</text>`;
  if (days[0].tmin_c != null) svg += `<text class="axis" x="${L - 6}" y="${yt(days[0].tmin_c) + 4}" text-anchor="end">${Math.round(days[0].tmin_c)}°</text>`;
  const every = narrow ? 2 : 1;
  days.forEach((d, i) => {
    if (i % every) return;
    const dt = parseDate(d.date);
    svg += `<text class="axis" x="${cx(i)}" y="${H - B + 16}" text-anchor="middle">${weekdayFn(d.date)}</text>`;
    svg += `<text class="axis" x="${cx(i)}" y="${H - B + 30}" text-anchor="middle">${dt.getUTCDate()} ${months()[dt.getUTCMonth()]}</text>`;
  });
  return svg + "</svg>";
}

/** Usage per day: stacked bars by channel. rows: [{date, web, ussd, app, api}] */
export function usageChart(rows, width, colors) {
  const W = Math.max(320, Math.round(width)), H = 200, L = 30, R = 8, T = 10, B = 26;
  const keys = Object.keys(colors);
  const totals = rows.map((r) => keys.reduce((s, k) => s + (r[k] || 0), 0));
  const max = Math.max(4, ...totals);
  const bw = (W - L - R) / Math.max(1, rows.length);
  const y = (v) => T + (1 - v / max) * (H - T - B);
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Recommendations per day">`;
  svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(max)}" y2="${y(max)}"/><text class="axis" x="${L - 4}" y="${y(max) + 4}" text-anchor="end">${max}</text>`;
  svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/><text class="axis" x="${L - 4}" y="${y(0) + 4}" text-anchor="end">0</text>`;
  rows.forEach((r, i) => {
    let acc = 0;
    keys.forEach((k) => {
      const v = r[k] || 0;
      if (!v) return;
      svg += `<rect x="${L + i * bw + 1}" y="${y(acc + v)}" width="${Math.max(1, bw - 2)}" height="${y(acc) - y(acc + v)}" fill="${colors[k]}"/>`;
      acc += v;
    });
    if (i % 7 === 0) {
      const d = parseDate(r.date);
      svg += `<text class="axis" x="${L + i * bw + bw / 2}" y="${H - 8}" text-anchor="middle">${d.getUTCDate()} ${months()[d.getUTCMonth()]}</text>`;
    }
  });
  return svg + "</svg>";
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * p;
}
