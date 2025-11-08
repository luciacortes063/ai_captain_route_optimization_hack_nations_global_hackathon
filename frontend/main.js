// =================== CONFIG ===================
const API_BASE = "http://localhost:8000"; 

// =================== DOM HOOKS ===================
const originSel   = document.getElementById("origin");
const destSel     = document.getElementById("dest");
const btn         = document.getElementById("btn");
const msg         = document.getElementById("msg");
const resultsEl   = document.getElementById("results");
const distanceEl  = document.getElementById("distance");
const etaEl       = document.getElementById("eta");
const piracyEl    = document.getElementById("piracy");
const weatherEl   = document.getElementById("weather");
const explEl      = document.getElementById("explanations");
const toggleRisk  = document.getElementById("toggleRisk");

// Helpers
function setControlsEnabled(enabled) {
  originSel.disabled = !enabled;
  destSel.disabled   = !enabled;
  btn.disabled       = !enabled;
}
function setRiskToggleEnabled(enabled) {
  toggleRisk.disabled = !enabled;
}

// =================== MAP ===================

// Region limits
const latRange = [-10.0, 35.0];
const lonRange = [30.0, 65.0];
const southWest = L.latLng(latRange[0], lonRange[0]);
const northEast = L.latLng(latRange[1], lonRange[1]);
const bounds = L.latLngBounds(southWest, northEast);

// Map with hard pan limits
const map = L.map("map", {
  zoomControl: true,
  maxBounds: bounds,
  maxBoundsViscosity: 1.0,
  worldCopyJump: false
});

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "&copy; OpenStreetMap contributors",
  noWrap: true
}).addTo(map);

const CENTER_LNG = bounds.getCenter().lng;

// ---- compute a zoom that fits the region width
function zoomToFitWidth(m, b, maxZ = 18) {
  const sizeX = m.getSize().x;
  let chosen = 0;
  for (let z = Math.min(maxZ, 18); z >= 0; z--) {
    const pSW = m.options.crs.latLngToPoint(b.getSouthWest(), z);
    const pNE = m.options.crs.latLngToPoint(b.getNorthEast(), z);
    const widthPx = Math.abs(pNE.x - pSW.x);
    if (widthPx <= sizeX) { chosen = z; break; }
  }
  return chosen;
}

// ---- non-reentrant fit + lock
let _fitting = false;
function fitWidthAndLock() {
  if (_fitting) return;
  _fitting = true;
  try {
    map.invalidateSize();                       
    const z = zoomToFitWidth(map, bounds, 8);   
    map.setView(bounds.getCenter(), z, { animate: false });
    map.setMinZoom(z);                          
    map.setMaxZoom(8);                          
    map.panInsideBounds(bounds, { animate: false });
    clampHorizontalAtMinZoom();                 
  } finally {
    setTimeout(() => { _fitting = false; }, 0);
  }
}

// ---- guarded horizontal clamp at min-zoom
const _clampBusy = { v: false };
function clampHorizontalAtMinZoom() {
  if (_clampBusy.v) return;
  if (map.getZoom() !== map.getMinZoom()) return;

  const c = map.getCenter();
  if (Math.abs(c.lng - CENTER_LNG) > 1e-6) {        // avoid jitter
    _clampBusy.v = true;
    map.panTo([c.lat, CENTER_LNG], { animate: false });
    map.once('moveend', () => { _clampBusy.v = false; });
  }
}

map.on("moveend", clampHorizontalAtMinZoom);
map.on("zoomend", clampHorizontalAtMinZoom);
setTimeout(fitWidthAndLock, 0);
map.whenReady(fitWidthAndLock);
window.addEventListener("resize", fitWidthAndLock);
map.on("move", clampHorizontalAtMinZoom);
map.on("zoomend", clampHorizontalAtMinZoom);

// Layers
let routeLayer = null;
let hazardLayers = [];

function clearRoute() {
  if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
}
function clearHazards() {
  for (const l of hazardLayers) map.removeLayer(l);
  hazardLayers = [];
}

// ---- hardened route draw + safe fit
function drawRouteFromCoordinates(rawCoords) {
  if (!Array.isArray(rawCoords)) return;

  // sanitize points
  const coords = [];
  for (const p of rawCoords) {
    if (!Array.isArray(p) || p.length < 2) continue;
    let lat = Number(p[0]);
    let lng = Number(p[1]);

    // if swapped or bizarre ranges, attempt flip
    if ((Math.abs(lat) > 90 && Math.abs(lng) <= 90) || Math.abs(lat) > 180) {
      const t = lat; lat = lng; lng = t;
    }

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) continue;

    coords.push([lat, lng]);
  }

  if (coords.length < 2) return;

  if (routeLayer) map.removeLayer(routeLayer);
  routeLayer = L.polyline(coords, { weight: 4, color: "#d00" }).addTo(map);

  let b = L.latLngBounds(coords);
  // protect degenerate bounds
  if (b.getNorth() === b.getSouth() || b.getEast() === b.getWest()) {
    b = b.pad(0.0001);
  }
  // keep within global region
  if (!bounds.intersects(b)) {
    b = L.latLngBounds([
      b.getSouthWest(), b.getNorthEast(),
      bounds.getSouthWest(), bounds.getNorthEast()
    ]);
  }

  try {
    map.fitBounds(b.pad(0.2), { maxZoom: map.getMaxZoom() });
  } catch (err) {
    console.error("fitBounds failed for route bounds:", b, err);
    return;
  }

  // defer clamp to avoid immediate re-entrancy after fit
  setTimeout(() => clampHorizontalAtMinZoom(), 0);
}

function drawRiskLayers(layers) {
  clearHazards();
  for (const layer of layers || []) {
    const color = layer.type === "piracy" ? "orange" : "deepskyblue";
    for (const f of layer.features || []) {
      const poly = L.polygon(f.polygon, { color, weight: 1, fillOpacity: 0.25 });
      poly.addTo(map);
      hazardLayers.push(poly);
    }
  }
}

// =================== API HELPERS ===================
async function apiGet(path, params = {}) {
  const url = new URL(path, API_BASE);
  Object.entries(params).forEach(([k,v]) => v!=null && url.searchParams.set(k, v));

  let res;
  try {
    res = await fetch(url.toString());
  } catch (e) {
    console.error(`[GET ${url}] Network error:`, e);
    throw new Error(`Network error calling ${url}`);
  }

  const text = await res.text();   // read raw text first
  if (!res.ok) {
    console.error(`[GET ${url}] HTTP ${res.status}:`, text);
    throw new Error(text || `GET ${url} failed with ${res.status}`);
  }

  try {
    return JSON.parse(text);
  } catch (e) {
    console.error(`[GET ${url}] Invalid JSON:`, text);
    throw new Error(`Invalid JSON from ${url}`);
  }
}

async function apiPost(path, body) {
  const res = await fetch(new URL(path, API_BASE).toString(), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// =================== PORTS  ===================
function withinZone(p) {
  return (
    typeof p.latitude === "number" &&
    typeof p.longitude === "number" &&
    p.latitude  >= latRange[0] && p.latitude  <= latRange[1] &&
    p.longitude >= lonRange[0] && p.longitude <= lonRange[1]
  );
}

async function loadPorts() {
  setControlsEnabled(false);
  const data = await apiGet("/ports", { limit: 2000, offset: 0 });
  const ports = (data?.ports ?? []).filter(withinZone);

  originSel.innerHTML = "";
  destSel.innerHTML   = "";

  ports.forEach(p => {
    const label = `${p.name} (${p.id}, ${p.country})`;
    const val = p.id;
    originSel.appendChild(new Option(label, val));
    destSel.appendChild(new Option(label, val));
  });

  if (ports.length === 0) {
    msg.textContent = "No ports available in the current zone.";
    setControlsEnabled(false);
    return;
  }

  originSel.selectedIndex = 0;
  destSel.selectedIndex   = ports.length > 1 ? 1 : 0;
  msg.textContent = "";
  setControlsEnabled(true);
}

// =================== RISK LAYERS (optional) ===================
async function loadRiskLayers() {
  try {
    const data = await apiGet("/risk-layers");
    drawRiskLayers(data?.layers ?? []);
  } catch {
    clearHazards();
  }
}

// =================== ROUTE ===================
function getMode() {
  const r = document.querySelector('input[name="mode"]:checked');
  return r ? r.value : "safe";
}

function setResults(route) {
  const s = route?.summary || {};
  resultsEl.classList.remove("hidden");
  distanceEl.textContent = s.totalDistanceNm != null ? `${s.totalDistanceNm.toFixed?.(1)} nm` : "–";
  etaEl.textContent      = s.estimatedDurationHours != null ? `${s.estimatedDurationHours.toFixed?.(1)} h` : "–";
  piracyEl.textContent   = s.totalPiracyRisk != null ? s.totalPiracyRisk.toFixed?.(2) : "–";
  weatherEl.textContent  = s.totalWeatherRisk != null ? s.totalWeatherRisk.toFixed?.(2) : "–";

  const exp = route?.explanation || {};
  const lines = []
    .concat(exp.highLevel || [])
    .concat(exp.tradeoffs || []);
  explEl.innerHTML = "";
  lines.forEach(t => {
    const li = document.createElement("li");
    li.textContent = t;
    explEl.appendChild(li);
  });
}

async function calculateRoute() {
  msg.textContent = "";
  resultsEl.classList.add("hidden");
  clearRoute();

  const origin_portId = originSel.value || null;
  const dest_portId   = destSel.value || null;
  const mode          = getMode();

  if (!origin_portId || !dest_portId) {
    msg.textContent = "Select valid origin and destination ports.";
    return;
  }

  btn.disabled = true;
  btn.textContent = "Calculating…";

  try {
    const body = {
      origin:      { type: "port", portId: origin_portId },
      destination: { type: "port", portId: dest_portId },
      mode
    };

    const route = await apiPost("/route", body);

    const coords = route?.path?.coordinates ?? [];
    if (coords.length >= 2) {
      drawRouteFromCoordinates(coords);
    } else {
      msg.textContent = "No coordinates returned by /route.";
    }

    setResults(route);

    if (toggleRisk.checked) {
      await loadRiskLayers();
    } else {
      clearHazards();
    }
  } catch (e) {
    msg.textContent = e?.message || "Request failed";
  } finally {
    btn.disabled = false;
    btn.textContent = "Calculate route";
  }
}

// =================== WIRE UP ===================
btn.addEventListener("click", calculateRoute);
toggleRisk.addEventListener("change", async () => {
  if (toggleRisk.checked) await loadRiskLayers();
  else clearHazards();
});

// =================== INIT ===================
(async function init() {
  setControlsEnabled(false);
  setRiskToggleEnabled(true);

  try { await apiGet("/health"); } catch {}

  try {
    await loadPorts();
  } catch (e) {
    originSel.innerHTML = "";
    destSel.innerHTML   = "";
    msg.textContent = "Ports API not available yet. Start the backend to enable routing.";
    setControlsEnabled(false);
  }

  if (toggleRisk.checked) {
    await loadRiskLayers().catch(() => {});
  }
})();
