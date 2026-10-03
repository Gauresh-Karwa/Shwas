export const CATS = [
  { label: 'Good', min: 0, max: 50, color: '#3E9C78' },
  { label: 'Satisfactory', min: 51, max: 100, color: '#A3B94F' },
  { label: 'Moderate', min: 101, max: 200, color: '#E0B341' },
  { label: 'Poor', min: 201, max: 300, color: '#E08A3C' },
  { label: 'Very Poor', min: 301, max: 400, color: '#C4483F' },
  { label: 'Severe', min: 401, max: 500, color: '#7A2E3A' },
];

export function getCategory(aqi) {
  if (aqi == null) return { label: 'No data', min: 0, max: 500, color: '#D5E3DA' };
  for (const c of CATS) if (aqi <= c.max) return c;
  return CATS[CATS.length - 1];
}

export function getAQIColor(aqi) {
  return getCategory(aqi).color;
}

// ── CPCB sub-index breakpoints (same table as backend/app/aqi/breakpoints.py)
// Each band: [concLow, concHigh, indexLow, indexHigh]
const BREAKPOINTS = {
  'PM2.5': [[0, 30, 0, 50], [31, 60, 51, 100], [61, 90, 101, 200], [91, 120, 201, 300], [121, 250, 301, 400], [251, 10000, 401, 500]],
  'PM10': [[0, 50, 0, 50], [51, 100, 51, 100], [101, 250, 101, 200], [251, 350, 201, 300], [351, 430, 301, 400], [431, 10000, 401, 500]],
  'NO2': [[0, 40, 0, 50], [41, 80, 51, 100], [81, 180, 101, 200], [181, 280, 201, 300], [281, 400, 301, 400], [401, 10000, 401, 500]],
  'SO2': [[0, 40, 0, 50], [41, 80, 51, 100], [81, 380, 101, 200], [381, 800, 201, 300], [801, 1600, 301, 400], [1601, 100000, 401, 500]],
};

// Station field name → CPCB pollutant id
const POLLUTANT_FIELDS = { pm25: 'PM2.5', pm10: 'PM10', no2: 'NO2', so2: 'SO2' };

export function subIndex(pollutant, conc) {
  const bands = BREAKPOINTS[pollutant];
  if (!bands || conc == null || conc < 0) return null;
  for (const [cLow, cHigh, iLow, iHigh] of bands) {
    if (conc >= cLow && conc <= cHigh) {
      if (cHigh === cLow) return iLow;
      return iLow + ((conc - cLow) / (cHigh - cLow)) * (iHigh - iLow);
    }
  }
  return bands[bands.length - 1][3];
}

export function dominantPollutant(readings) {
  let best = null, bestIdx = -1;
  for (const [field, id] of Object.entries(POLLUTANT_FIELDS)) {
    const idx = subIndex(id, readings?.[field]);
    if (idx != null && idx > bestIdx) { best = id; bestIdx = idx; }
  }
  return best;
}