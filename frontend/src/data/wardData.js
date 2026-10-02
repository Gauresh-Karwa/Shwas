/**
 * wardData.js  — shared singleton module
 *
 * Loads BMC_Wards.geojson (24 administrative ward polygons) and
 * ward_level_collated.csv (population per ward), joins them by
 * Ward_Alphabet / name, then exports a single Promise that resolves
 * to { geojson, popByWard, bounds }.
 *
 * The same resolved geojson is reused by the heatmap clipping step.
 *
 * Ward code normalisation:  "K/E", "K-E", "k e", "ke" → "K/E"
 * (upper-case, collapse spaces/hyphens/underscores → "/")
 */

import Papa from 'papaparse';

// ── normalise a ward code string ──────────────────────────────────
export function normaliseWard(raw) {
  if (!raw) return '';
  return String(raw)
    .trim()
    .toUpperCase()
    .replace(/[\s\-_]+/g, '/')
    .replace(/\/+/g, '/');
}

// ── parse CSV text via PapaParse ──────────────────────────────────
function parseCSV(text) {
  const result = Papa.parse(text, { header: true, skipEmptyLines: true });
  return result.data;
}

// ── compute bounding box of a GeoJSON FeatureCollection ──────────
function computeBounds(fc) {
  let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
  for (const feat of fc.features) {
    const coords = flattenCoords(feat.geometry);
    for (const [lng, lat] of coords) {
      if (lng < minLng) minLng = lng;
      if (lat < minLat) minLat = lat;
      if (lng > maxLng) maxLng = lng;
      if (lat > maxLat) maxLat = lat;
    }
  }
  return [[minLng, minLat], [maxLng, maxLat]]; // [[sw], [ne]]
}

function flattenCoords(geom) {
  if (!geom) return [];
  const type = geom.type;
  if (type === 'Point')            return [geom.coordinates];
  if (type === 'MultiPoint')       return geom.coordinates;
  if (type === 'LineString')       return geom.coordinates;
  if (type === 'MultiLineString')  return geom.coordinates.flat();
  if (type === 'Polygon')          return geom.coordinates.flat();
  if (type === 'MultiPolygon')     return geom.coordinates.flat(2);
  if (type === 'GeometryCollection') return geom.geometries.flatMap(flattenCoords);
  return [];
}

// ── singleton promise ─────────────────────────────────────────────
let _promise = null;

export function loadWardData() {
  if (_promise) return _promise;

  _promise = (async () => {
    // 1 – Load GeoJSON (24 administrative wards – the authoritative boundary file)
    const geoRes = await fetch('/data/BMC_Wards.geojson');
    if (!geoRes.ok) throw new Error('Failed to load BMC_Wards.geojson');
    const geojson = await geoRes.json();

    // 2 – Load population CSV
    const csvRes = await fetch('/data/ward_level_collated.csv');
    if (!csvRes.ok) throw new Error('Failed to load ward_level_collated.csv');
    const csvText = await csvRes.text();
    const csvRows = parseCSV(csvText);

    // 3 – Build population lookup: normalisedWardCode → TOT_P (number)
    const popByWard = {};
    for (const row of csvRows) {
      const key = normaliseWard(row.Ward_Alphabet);
      if (key) popByWard[key] = parseInt(row.TOT_P, 10) || 0;
    }

    // 4 – Annotate each ward feature with population + normalised code
    const wardNames = new Set(csvRows.map(r => normaliseWard(r.Ward_Alphabet)));
    const unmatched = [];

    const annotated = {
      ...geojson,
      features: geojson.features.map(f => {
        const rawCode = f.properties.name;
        const code    = normaliseWard(rawCode);
        const pop     = popByWard[code] ?? null;
        if (pop === null) unmatched.push(rawCode);
        return {
          ...f,
          id: code,          // used as promoteId in MapLibre
          properties: {
            ...f.properties,
            wardCode: code,
            population: pop,
            wardName:   rawCode,
          },
        };
      }),
    };

    // 5 – Dev-mode warnings for unmatched wards
    if (unmatched.length > 0) {
      console.warn('[wardData] Unmatched ward codes (no population data):', unmatched);
    }

    // 6 – Compute bounds
    const bounds = computeBounds(annotated);

    return { geojson: annotated, popByWard, bounds, unmatched };
  })();

  return _promise;
}
