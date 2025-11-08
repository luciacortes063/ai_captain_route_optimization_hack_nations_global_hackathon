// =================== CONFIG ===================
const API_BASE = "http://localhost:8000"; // adjust if needed

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

function fitWidthAndLock() {
  map.invalidateSize();                       // ensure container size is known
  const z = zoomToFitWidth(map, bounds, 8);   // cap to a sane max (8 looks good for this region)
  map.setView(bounds.getCenter(), z, { animate: false });
  map.setMinZoom(z);                          // can't zoom out past width-fit
  map.setMaxZoom(8);                          // can zoom in
  map.panInsideBounds(bounds, { animate: false });
  clampHorizontalAtMinZoom();                 // keep horizontal fixed at min zoom
}

// Lock horizontal panning at min zoom so left/right edges stay aligned with the screen
function clampHorizontalAtMinZoom() {
  if (map.getZoom() !== map.getMinZoom()) return;
  const c = map.getCenter();
  if (Math.abs(c.lng - CENTER_LNG) > 1e-9) {
    map.panTo([c.lat, CENTER_LNG], { animate: false });
  }
}

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

function drawRouteFromCoordinates(coords) {
  if (!Array.isArray(coords) || coords.length < 2) return;
  if (routeLayer) map.removeLayer(routeLayer);

  routeLayer = L.polyline(coords, { weight: 4, color: "#d00" }).addTo(map);

  // Fit to route but never zoom out below the width-fit level
  map.fitBounds(L.latLngBounds(coords).pad(0.2), {
    maxZoom: map.getMaxZoom()
  });
  clampHorizontalAtMinZoom();
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
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(await res.text());
  return res.json();
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
