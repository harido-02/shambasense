// Leaflet map for picking a farm. Falls back to a message when the map cannot load (offline).
import { KENYA } from "./config.js";

export function createMap(el, { counties = [], onPick, onCounty, center = [0.1, 36.6], zoom = 6, missingText = "" }) {
  if (!window.L) {
    el.classList.add("map-missing");
    el.textContent = missingText;
    return { setMarker() {}, flyTo() {}, invalidate() {}, available: false };
  }
  const map = L.map(el, { scrollWheelZoom: false, tap: true, maxBounds: [[KENYA.south - 2, KENYA.west - 2], [KENYA.north + 2, KENYA.east + 2]] })
    .setView(center, zoom);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 15, attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  L.Icon.Default.imagePath = "/static/vendor/leaflet/images/";
  counties.forEach((c) => {
    L.circleMarker([c.lat, c.lon], { radius: 7, color: "#1F5E3B", weight: 2, fillColor: "#FFFFFF", fillOpacity: 1 })
      .bindTooltip(c.name).addTo(map)
      .on("click", (e) => { L.DomEvent.stopPropagation(e); onCounty && onCounty(c.id); });
  });
  let marker = null;
  map.on("click", (e) => onPick && onPick(e.latlng.lat, e.latlng.lng));
  return {
    available: true,
    setMarker(lat, lon) {
      if (!marker) marker = L.marker([lat, lon]).addTo(map);
      else marker.setLatLng([lat, lon]);
    },
    flyTo(lat, lon, z = 9) { map.flyTo([lat, lon], z, { duration: 0.5 }); },
    invalidate() { setTimeout(() => map.invalidateSize(), 50); },
  };
}

export function inKenya(lat, lon) {
  return lat >= KENYA.south && lat <= KENYA.north && lon >= KENYA.west && lon <= KENYA.east;
}

export function locate() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) { reject(new Error("unsupported")); return; }
    navigator.geolocation.getCurrentPosition((p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      (err) => reject(err), { enableHighAccuracy: true, timeout: 15000, maximumAge: 300000 });
  });
}

export function nearestCounty(counties, lat, lon) {
  const r = Math.PI / 180;
  let best = null, bestD = Infinity;
  counties.forEach((c) => {
    const dLat = (c.lat - lat) * r, dLon = (c.lon - lon) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat * r) * Math.cos(c.lat * r) * Math.sin(dLon / 2) ** 2;
    const d = 12742 * Math.asin(Math.sqrt(h));
    if (d < bestD) { best = c; bestD = d; }
  });
  return { county: best, km: bestD };
}
