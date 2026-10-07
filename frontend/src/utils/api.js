/**
 * api.js — all network calls to the FastAPI backend.
 *
 * Rules:
 *  - No API keys here. The backend holds all credentials.
 *  - Every function throws on HTTP error so callers can catch and show
 *    the "Backend unreachable" banner.
 *  - VITE_API_BASE_URL controls the base URL (.env.local).
 */

import { getCategory } from './aqi';
import { loadWardData } from '../data/wardData';
import { ptInFeature } from './geo';

const BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

// ── Health check — used to detect if backend is reachable ──────────
export async function checkHealth(signal) {
  const res = await fetch(`${BASE}/health`, { signal });
  if (!res.ok) throw new Error(`health HTTP ${res.status}`);
  const data = await res.json(); // { status: "ok" }
  return { data, timestamp: res.headers.get('date') || new Date().toISOString() };
}

// ── /api/interpolate ───────────────────────────────────────────────
// Returns: { lat, lon, estimated_aqi, model, stations_used, confidence? }
export async function interpolate(lat, lon, signal) {
  const url = `${BASE}/api/interpolate?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}`;
  const res = await fetch(url, signal ? { signal } : {});
  if (!res.ok) throw new Error(`interpolate HTTP ${res.status}`);
  return res.json();
}

function distance(lat1, lon1, lat2, lon2) {
  const R = 6371e3; // metres
  const phi1 = lat1 * Math.PI / 180;
  const phi2 = lat2 * Math.PI / 180;
  const deltaPhi = (lat2 - lat1) * Math.PI / 180;
  const deltaLambda = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(deltaPhi / 2) * Math.sin(deltaPhi / 2) +
    Math.cos(phi1) * Math.cos(phi2) *
    Math.sin(deltaLambda / 2) * Math.sin(deltaLambda / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

function normalizeName(name) {
  if (!name) return "";
  return name.toLowerCase().replace(/\s*\(.*?\)\s*/g, '').replace(/[^a-z0-9]/g, '');
}

function mergeStations(backendStations, configStations) {
  const merged = [];

  for (const bs of backendStations) {
    let lat = bs.lat;
    let lon = bs.lon;
    let ward = bs.ward;
    let agency = bs.agency;
    let name = bs.name;

    // Attempt to match by id or name to get coordinates if missing
    if (!lat || !lon) {
      const config = configStations.find(c => c.id === bs.id || c.name === bs.name);
      if (config) {
        lat = config.lat;
        lon = config.lon;
        ward = config.ward || ward;
        agency = config.agency || agency;
        name = config.name || name;
      }
    }

    const bsNormName = normalizeName(name);
    let matchIdx = -1;
    for (let i = 0; i < merged.length; i++) {
      const ms = merged[i];
      const msNormName = normalizeName(ms.name);
      const sameName = bsNormName && msNormName && bsNormName === msNormName;
      const near = (lat && lon && ms.lat && ms.lon) ? distance(lat, lon, ms.lat, ms.lon) <= 300 : false;

      if (sameName || near) {
        matchIdx = i;
        break;
      }
    }

    const stationEntry = {
      ...bs,
      name, lat, lon, ward, agency,
      aqi: bs.aqi ?? null,
      pm25: bs.pm25 ?? null,
      pm10: bs.pm10 ?? null,
      no2: bs.no2 ?? null,
      so2: bs.so2 ?? null,
      updated_at: bs.updated_at ?? null,
    };

    if (matchIdx >= 0) {
      // Merge, keep newer reading
      const existing = merged[matchIdx];
      const t1 = existing.updated_at ? new Date(existing.updated_at).getTime() : 0;
      const t2 = stationEntry.updated_at ? new Date(stationEntry.updated_at).getTime() : 0;
      if (t2 > t1) {
        merged[matchIdx] = { ...existing, ...stationEntry, id: existing.id };
      }
    } else {
      merged.push(stationEntry);
    }
  }

  return merged;
}

// ── fetchLiveStations ──────────────────────────────────────────────
// Backend sends: station_id, name ("Powai, Mumbai - MPCB"), lat, lon, aqi, timestamp, pollutants.
// It does NOT send ward or agency, so we work them out from live data:
//   agency → from the name suffix
//   ward   → which ward polygon contains the station's lat/lon

const AGENCY_RE = /\s*-\s*(MPCB|IITM|BMC|CPCB|SAFAR)\s*$/i;

function agencyFromName(name) {
  const m = (name ?? '').match(AGENCY_RE);
  return m ? m[1].toUpperCase() : null;
}

function cleanStationName(name) {
  return (name ?? '')
    .replace(AGENCY_RE, '')          // drop " - MPCB"
    .replace(/,\s*Mumbai\s*$/i, '')  // drop ", Mumbai"
    .replace(/_/g, ', ')             // "Kherwadi_Bandra East" → "Kherwadi, Bandra East"
    .trim();
}

// First argument is no longer used (seed list removed); kept so callers don't break.
export async function fetchLiveStations(signal) {
  const url = `${BASE}/api/stations`;
  const res = await fetch(url, signal ? { signal } : {});
  if (!res.ok) throw new Error('Failed to fetch live stations');
  const data = await res.json();

  if (data.length === 0) {
    throw new Error('No live data available from any station');
  }

  // Ward polygons (real file). If it fails to load, ward just stays null.
  let wardFeatures = [];
  try {
    wardFeatures = (await loadWardData()).geojson.features;
  } catch { /* ward stays null */ }

  const wardOf = (lat, lon) => {
    if (lat == null || lon == null) return null;
    const f = wardFeatures.find(feat => ptInFeature(lon, lat, feat)); // note: lon first
    return f ? f.properties.wardCode : null;
  };

  const backendStations = data.map(s => ({
    id: s.station_id,
    name: cleanStationName(s.name),
    agency: agencyFromName(s.name),
    ward: wardOf(s.lat, s.lon),
    lat: s.lat,
    lon: s.lon,
    aqi: s.aqi != null ? Math.round(s.aqi) : null,
    updated_at: s.timestamp,
    pm25: s.pm25 ?? null,
    pm10: s.pm10 ?? null,
    no2: s.no2 ?? null,
    so2: s.so2 ?? null,
  }));

  return mergeStations(backendStations, []);
}

// ── /api/forecast/{station_id} ─────────────────────────────────────
// Returns: { station_id, forecast: [{timestamp, aqi, aqi_lower?, aqi_upper?}] }

// Round numbers (100.3 → 100) and never go below 0
function cleanForecast(points) {
  if (!Array.isArray(points)) return null;
  const r = v => (v == null ? null : Math.max(0, Math.round(v)));
  return points.map(p => ({
    ...p,
    aqi: r(p.aqi),
    aqi_lower: r(p.aqi_lower),
    aqi_upper: r(p.aqi_upper),
  }));
}

export async function forecastStation(stationId, steps = 24, uncertainty = false) {
  const url = `${BASE}/api/forecast/${encodeURIComponent(stationId)}?steps=${steps}&uncertainty=${uncertainty}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`forecast HTTP ${res.status}`);
  const data = await res.json();
  const raw = data.forecast ?? data.forecasts ?? (Array.isArray(data) ? data : null);
  return { ...data, forecast: cleanForecast(raw) };
}

// ── /api/forecast/coordinate ───────────────────────────────────────
export async function forecastCoordinate(lat, lon, steps = 24, uncertainty = false) {
  const url = `${BASE}/api/forecast/coordinate?lat=${lat.toFixed(6)}&lon=${lon.toFixed(6)}&steps=${steps}&uncertainty=${uncertainty}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`forecast/coordinate HTTP ${res.status}`);
  const data = await res.json();
  return { ...data, forecast: cleanForecast(data.forecast) };
}

// ── /api/attribution ───────────────────────────────────────────────
// Returns: { wind, fires: [{ lat, lon, distance_km, frp_mw }],
//            news: [{ title, url, domain }], explanation,
//            air_mass: back-trajectory { points, origin, over, fires_on_path, summary, ... } | null }
export async function getAttribution(lat, lon, stationName, aqi, category, dominantPollutant) {
  const params = new URLSearchParams({
    lat: lat.toFixed(6),
    lon: lon.toFixed(6),
    station_name: stationName,
    aqi: String(Math.round(aqi ?? 0)),
    category: category,
    dominant_pollutant: dominantPollutant,
  });
  const res = await fetch(`${BASE}/api/attribution?${params}`);
  if (!res.ok) throw new Error(`attribution HTTP ${res.status}`);
  return res.json();
}

// ctx: { lat, lon, aqi, name, dominantPollutant? }
// Category is always derived from the AQI so text and header never disagree.
// dominantPollutant falls back to 'PM2.5' (backend default) only when no
// pollutant reading is available for the location.
export async function getAttributionFor(ctx) {
  const aqi = Math.round(ctx.aqi ?? 0);
  return getAttribution(
    ctx.lat, ctx.lon,
    ctx.name ?? 'Unknown location',
    aqi,
    getCategory(aqi).label,
    ctx.dominantPollutant ?? 'mixed pollutants',
  );
}

// ── /api/wards ─────────────────────────────────────────────────────
// Returns: { status, stations_used, wards, population_by_category, total_population }
export async function fetchWardExposure(signal) {
  const res = await fetch(`${BASE}/api/wards`, signal ? { signal } : {});
  if (!res.ok) throw new Error(`wards HTTP ${res.status}`);
  return res.json();
}

// ── /api/analytics/hotspots ────────────────────────────────────────
// Returns: [{ lat, lon, ward_id, ward_name, population, estimated_aqi,
//             uncertainty_std, lcb, lcb_category, method }]
export async function fetchHotspots(threshold = 100, z = 1.0, signal) {
  const url = `${BASE}/api/analytics/hotspots?threshold=${threshold}&z=${z}`;
  const res = await fetch(url, signal ? { signal } : {});
  if (!res.ok) throw new Error(`hotspots HTTP ${res.status}`);
  return res.json();
}

// ── /api/recommendations/sensor-placement ─────────────────────────
// Returns: [{ lat, lon, ward_id, ward_name, population,
//             estimated_aqi, uncertainty_std, nearest_station_distance_km, score,
//             reason: 'unmonitored_ward' | 'coverage_gap' }]
export async function fetchSensorSites(topK = 12, signal) {
  const url = `${BASE}/api/recommendations/sensor-placement?top_k=${topK}`;
  const res = await fetch(url, signal ? { signal } : {});
  if (!res.ok) throw new Error(`sensor-placement HTTP ${res.status}`);
  return res.json();
}

// ── /api/attribution/{station_id}/apportionment ────────────────────
// Returns: { source_type, fine_fraction, interpretation, data_available, ... }
export async function fetchApportionment(stationId, signal) {
  const url = `${BASE}/api/attribution/${encodeURIComponent(stationId)}/apportionment`;
  const res = await fetch(url, signal ? { signal } : {});
  if (!res.ok) throw new Error(`apportionment HTTP ${res.status}`);
  return res.json();
}

// ── /api/waste/burning ─────────────────────────────────────────────
export async function fetchWasteBurning(simulate = false, signal) {
  const url = `${BASE}/api/waste/burning${simulate ? '?simulate=true' : ''}`;
  const res = await fetch(url, signal ? { signal } : {});
  if (!res.ok) throw new Error(`waste-burning HTTP ${res.status}`);
  return res.json();
}