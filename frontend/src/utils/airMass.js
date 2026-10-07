// Helpers for the air-mass back-trajectory returned by /api/attribution
// as `air_mass` (see backend/app/attribution/trajectory.py).
//
// air_mass.points run from the station (hours_back 0) back to where the
// air was `hours` hours earlier. On the map the line is drawn the other
// way round, oldest to newest, so it reads as the air travelling to the
// station.

const MIN_VISIBLE_KM = 1; // shorter than this is "barely moved": nothing to draw

const COMPASS_WORDS = [
  'north', 'north-east', 'east', 'south-east',
  'south', 'south-west', 'west', 'north-west',
];

function compassWordsFromBearing(deg) {
  if (deg == null) return null;
  return COMPASS_WORDS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}

function hasPath(airMass) {
  return Boolean(
    airMass &&
    Array.isArray(airMass.points) &&
    airMass.points.length >= 2 &&
    (airMass.origin?.distance_km ?? 0) >= MIN_VISIBLE_KM,
  );
}

const EMPTY = { type: 'FeatureCollection', features: [] };

// One GeoJSON collection: the path as a LineString plus a Point per hour.
export function airMassFeatureCollection(airMass) {
  if (!hasPath(airMass)) return EMPTY;

  const oldestFirst = [...airMass.points].sort((a, b) => b.hours_back - a.hours_back);
  const line = {
    type: 'Feature',
    properties: { kind: 'path' },
    geometry: { type: 'LineString', coordinates: oldestFirst.map(p => [p.lon, p.lat]) },
  };

  const oldest = oldestFirst[0].hours_back;
  const dots = oldestFirst
    .filter(p => p.hours_back > 0)
    .map(p => ({
      type: 'Feature',
      properties: {
        kind: 'hour',
        hours_back: p.hours_back,
        origin: p.hours_back === oldest,
        label: p.hours_back === oldest ? `${p.hours_back} h ago` : `${p.hours_back} h`,
      },
      geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
    }));

  return { type: 'FeatureCollection', features: [line, ...dots] };
}

// [[west, south], [east, north]] around the path, or null when nothing is drawn.
export function airMassBounds(airMass) {
  if (!hasPath(airMass)) return null;
  const lons = airMass.points.map(p => p.lon);
  const lats = airMass.points.map(p => p.lat);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

// Short text for the right panel. Returns null when the API sent no trajectory.
export function describeAirMass(airMass) {
  if (!airMass) return null;

  if (airMass.stagnant) {
    return {
      headline: `Winds were light (about ${Number(airMass.mean_speed_mps).toFixed(1)} m/s)`,
      detail: 'The air moved slowly, so pollutants are not being dispersed quickly.',
    };
  }

  const from = compassWordsFromBearing(airMass.origin?.bearing_deg);
  const headline = from
    ? `From the ${from}, ${Math.round(airMass.path_km)} km in ${airMass.hours} h`
    : `${Math.round(airMass.path_km)} km in ${airMass.hours} h`;

  const route = [];
  if (airMass.over?.sea && airMass.over.marine_hours != null) {
    route.push(`Over the sea for at least ${Math.floor(airMass.over.marine_hours)} h`); // floor: never overstate a lower bound
  }
  const wards = (airMass.over?.wards ?? []).map(w => w.ward_name).filter(Boolean);
  if (wards.length) route.push(wards.join(' → '));

  return { headline, detail: route.length ? route.join(' · ') : null };
}
