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
const trafficEl   = document.getElementById("traffic");
const geoEl       = document.getElementById("geopolitics");
const alertsEl    = document.getElementById("routeAlerts");


// Overlays
const overlayModeRadios = document.querySelectorAll('input[name="overlayMode"]');
const riskLegend  = document.getElementById("riskLegend");
const safetyLegend = document.getElementById("safetyLegend");

// Helpers
function setControlsEnabled(enabled) {
  originSel.disabled = !enabled;
  destSel.disabled   = !enabled;
  btn.disabled       = !enabled;
}

function setOverlayControlsEnabled(enabled) {
  overlayModeRadios.forEach(r => r.disabled = !enabled);
}

function getOverlayMode() {
  const r = document.querySelector('input[name="overlayMode"]:checked');
  return r ? r.value : "none";
}

function updateLegends() {
  const mode = getOverlayMode();
  if (mode === "risk") {
    if (riskLegend) riskLegend.classList.remove("hidden");
    if (safetyLegend) safetyLegend.classList.add("hidden");
  } else if (mode === "safety") {
    if (riskLegend) riskLegend.classList.add("hidden");
    if (safetyLegend) safetyLegend.classList.remove("hidden");
  } else {
    if (riskLegend) riskLegend.classList.add("hidden");
    if (safetyLegend) safetyLegend.classList.add("hidden");
  }
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
  hazardLayers = [];
}

// --- Simple route smoothing with Chaikin's corner cutting ---
function smoothRoute(coords, iterations = 2) {
  if (!Array.isArray(coords) || coords.length < 3) return coords;

  let current = coords.map(p => [p[0], p[1]]); // copy

  for (let it = 0; it < iterations; it++) {
    const next = [];
    next.push(current[0]); // keep start

    for (let i = 0; i < current.length - 1; i++) {
      const [lat1, lon1] = current[i];
      const [lat2, lon2] = current[i + 1];

      const qLat = 0.75 * lat1 + 0.25 * lat2;
      const qLon = 0.75 * lon1 + 0.25 * lon2;
      const rLat = 0.25 * lat1 + 0.75 * lat2;
      const rLon = 0.25 * lon1 + 0.75 * lon2;

      next.push([qLat, qLon]);
      next.push([rLat, rLon]);
    }

    next.push(current[current.length - 1]); // keep end
    current = next;
  }

  return current;
}

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

  // smooth route
  const smoothCoords = smoothRoute(coords, 2);

  if (routeLayer) map.removeLayer(routeLayer);
  routeLayer = L.polyline(smoothCoords, { weight: 4, color: "#000000" }).addTo(map);
  routeLayer.bringToFront();   // 👈 ruta siempre encima

  let b = L.latLngBounds(smoothCoords);
  if (b.getNorth() === b.getSouth() || b.getEast() === b.getWest()) {
    b = b.pad(0.0001);
  }
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

  setTimeout(() => clampHorizontalAtMinZoom(), 0);
}

// =================== RISK LAYERS / SAFETY MAP ===================

function colorForSafety(sev) {
  // sev 1..5 -> verde → rojo
  switch (sev) {
    case 1: return "#00b050"; // very low
    case 2: return "#92d050"; // low
    case 3: return "#ffff00"; // medium
    case 4: return "#ff4d00ff"; // high
    case 5: return "#ff0000"; // very high
    default: return "#cccccc";
  }
}

function drawRiskLayers(layers) {
  clearHazards();

  const mode = getOverlayMode();
  if (mode === "none") {
    // no pintamos nada
    return;
  }

  for (const layer of layers || []) {
    // filtramos según modo
    if (mode === "risk" && layer.type === "safety") continue;
    if (mode === "safety" && layer.type !== "safety") continue;

    for (const f of layer.features || []) {
      const risk = f.riskLevel ?? f.severity ?? 0;

      let color;
      let fillOpacity = 0.25;

      if (layer.type === "piracy") {
        color = "orange";
      } else if (layer.type === "weather") {
        color = "deepskyblue";
      } else if (layer.type === "traffic") {
        color = "gray";
        if (risk >= 2) fillOpacity = 0.45;
        else if (risk === 1) fillOpacity = 0.3;
      } else if (layer.type === "geopolitics") {
        color = "red";
        if (risk >= 3) fillOpacity = 0.5;
        else if (risk >= 2) fillOpacity = 0.4;
        else fillOpacity = 0.3;
      } else if (layer.type === "safety") {
        color = colorForSafety(risk);
        fillOpacity = 0.35;
      } else {
        color = "pink";
      }

      const poly = L.polygon(f.polygon, { color, weight: 1, fillOpacity });
      poly.addTo(map);
      hazardLayers.push(poly);
    }
  }

  // Ruta siempre por encima de las capas
  if (routeLayer) routeLayer.bringToFront();
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

  const text = await res.text();
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

// =================== RISK LAYERS ===================
async function loadRiskLayers() {
  try {
    const data = await apiGet("/risk-layers");
    console.log("risk layers from API:", data); 
    drawRiskLayers(data?.layers ?? []);
  } catch (e) {
    console.error("Error loading risk layers:", e);
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

  distanceEl.textContent = s.totalDistanceNm != null
    ? `${s.totalDistanceNm.toFixed?.(1)} nm`
    : "–";

  etaEl.textContent = s.estimatedDurationHours != null
    ? `${s.estimatedDurationHours.toFixed?.(1)} h`
    : "–";

  piracyEl.textContent = s.totalPiracyRisk != null
    ? s.totalPiracyRisk.toFixed?.(2)
    : "–";

  weatherEl.textContent = s.totalWeatherRisk != null
    ? s.totalWeatherRisk.toFixed?.(2)
    : "–";

  if (trafficEl) {
    trafficEl.textContent = s.totalTrafficRisk != null
      ? s.totalTrafficRisk.toFixed?.(2)
      : "–";
  }

  if (geoEl) {
    geoEl.textContent = s.totalGeopoliticalRisk != null
      ? s.totalGeopoliticalRisk.toFixed?.(2)
      : "–";
  }

  const exp = route?.explanation || {};
  const rawLines = []
    .concat(exp.highLevel || [])
    .concat(exp.tradeoffs || []);

  const normalLines = [];
  const alertLines  = [];

  rawLines.forEach(t => {
    if (!t) return;
    if (t.startsWith("Route Alert:")) {
      alertLines.push(t);
    } else {
      normalLines.push(t);
    }
  });

  // Lista normal de explicaciones
  explEl.innerHTML = "";
  normalLines.forEach(t => {
    const li = document.createElement("li");
    li.textContent = t;
    explEl.appendChild(li);
  });

  // Pills de alerta
  if (alertsEl) {
    alertsEl.innerHTML = "";
    alertLines.forEach(t => {
      const pill = document.createElement("div");
      pill.className = "route-alert-pill";

      const label = document.createElement("span");
      label.className = "route-alert-label";
      label.textContent = "Route alert";

      const text = document.createElement("span");
      text.textContent = t.replace(/^Route Alert:\s*/i, "");

      pill.appendChild(label);
      pill.appendChild(text);
      alertsEl.appendChild(pill);
    });
  }
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

    const modeOverlay = getOverlayMode();
    if (modeOverlay !== "none") {
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

overlayModeRadios.forEach(r => {
  r.addEventListener("change", async () => {
    updateLegends();
    const mode = getOverlayMode();
    if (mode === "none") {
      clearHazards();
    } else {
      await loadRiskLayers().catch(() => {});
    }
  });
});

// =================== INIT ===================
(async function init() {
  setControlsEnabled(false);
  setOverlayControlsEnabled(true);
  updateLegends();

  try { await apiGet("/health"); } catch {}

  try {
    await loadPorts();
  } catch (e) {
    originSel.innerHTML = "";
    destSel.innerHTML   = "";
    msg.textContent = "Ports API not available yet. Start the backend to enable routing.";
    setControlsEnabled(false);
  }

  const modeOverlay = getOverlayMode();
  if (modeOverlay !== "none") {
    await loadRiskLayers().catch(() => {});
  }
})();
