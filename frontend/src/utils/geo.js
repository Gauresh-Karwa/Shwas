// ── Point-in-polygon (ray casting) ────────────────────────────────
export function ptInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    if (((yi > y) !== (yj > y)) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

export function ptInFeature(lng, lat, feat) {
  const g = feat.geometry;
  if (g.type === 'Polygon')
    return ptInRing(lng, lat, g.coordinates[0]);
  if (g.type === 'MultiPolygon')
    return g.coordinates.some(p => ptInRing(lng, lat, p[0]));
  return false;
}

export function isLand(lng, lat, features) {
  return features.some(f => ptInFeature(lng, lat, f));
}

// ── Compute ward AQI map ──────────────────────────────────────────
export function computeWardAqi(wardsGeoJSON, stations) {
  const wardsMap = {};
  const validStations = (stations ?? []).filter(s => s.aqi != null && s.aqi > 0);
  
  if (!wardsGeoJSON?.features?.length || !validStations.length) return wardsMap;

  wardsGeoJSON.features.forEach(ward => {
    const wardCode = ward.properties.wardCode;
    const coords = ward.geometry.coordinates;

    let sum = 0, count = 0;
    validStations.forEach(st => {
      if (ptInFeature(st.lon, st.lat, ward)) {
        sum += st.aqi;
        count++;
      }
    });

    if (count > 0) {
      wardsMap[wardCode] = { aqi: Math.round(sum / count), estimated: false, count };
    } else {
      // Find 3 nearest stations for IDW
      let cx = 0, cy = 0, pts = 0;
      if (ward.geometry.type === 'Polygon') {
        coords[0].forEach(([x, y]) => { cx += x; cy += y; pts++; });
      } else if (ward.geometry.type === 'MultiPolygon') {
        coords[0][0].forEach(([x, y]) => { cx += x; cy += y; pts++; });
      }
      if (pts > 0) {
        cx /= pts; cy /= pts;
      }

      const stationsWithDist = validStations.map(st => ({
        ...st,
        dist: Math.hypot(st.lon - cx, st.lat - cy)
      })).sort((a, b) => a.dist - b.dist);

      const nearest = stationsWithDist.slice(0, 3);
      
      let idwNum = 0, idwDen = 0;
      nearest.forEach(st => {
        const d = Math.max(st.dist, 1e-5);
        const w = 1 / (d * d);
        idwNum += w * st.aqi;
        idwDen += w;
      });
      
      const aqi = idwDen > 0 ? Math.round(idwNum / idwDen) : null;
      if (aqi !== null) {
        wardsMap[wardCode] = { aqi, estimated: true, count: 0 };
      }
    }
  });

  return wardsMap;
}
