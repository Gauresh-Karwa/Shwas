/* ── Station mock data ───────────────────────────────────────────
   Each station carries lat/lon/aqi/ward/agency + derived pollutants.
   Pollutants are approximate μg/m³ values realistic for Mumbai AQI.
─────────────────────────────────────────────────────────────────── */
function pollutantsFromAqi(aqi) {
  return {
    pm25: Math.max(2, Math.round(aqi * 0.55)),
    pm10: Math.max(5, Math.round(aqi * 1.00)),
    no2:  Math.max(5, Math.round(aqi * 0.19)),
    so2:  Math.max(2, Math.round(aqi * 0.12)),
  };
}

function withPoll(s) { 
  const aqi = s.aqi ?? (Math.floor(Math.random() * 300) + 50);
  return { ...s, aqi, ...pollutantsFromAqi(aqi) }; 
}

export const STATIONS = [
  withPoll({ id: 'kurla',       name: 'Kurla',                  ward: 'L',   agency: 'MPCB', lat: 19.0863, lon: 72.8888 }),
  withPoll({ id: 'sion',        name: 'Sion',                   ward: 'F/N', agency: 'MPCB', lat: 19.0470, lon: 72.8746 }),
  withPoll({ id: 'worli',       name: 'Worli',                  ward: 'G/S', agency: 'MPCB', lat: 18.9936, lon: 72.8128 }),
  withPoll({ id: 'mulund',      name: 'Mulund West',            ward: 'T',   agency: 'MPCB', lat: 19.1750, lon: 72.9419 }),
  withPoll({ id: 'powai',       name: 'Powai',                  ward: 'S',   agency: 'MPCB', lat: 19.1375, lon: 72.9151 }),
  withPoll({ id: 'malad',       name: 'Malad West',             ward: 'P/N', agency: 'IITM', lat: 19.1971, lon: 72.8220 }),
  withPoll({ id: 'chakala',     name: 'Andheri East',           ward: 'K/E', agency: 'IITM', lat: 19.1107, lon: 72.8608 }),
  withPoll({ id: 'shivaji',     name: 'Shivaji Nagar',          ward: 'M/E', agency: 'BMC',  lat: 19.0605, lon: 72.9234 }),
  withPoll({ id: 'airport',     name: 'CST Airport T2',         ward: 'K/E', agency: 'MPCB', lat: 19.1008, lon: 72.8746 }),
  withPoll({ id: 'bkc',        name: 'Bandra Kurla Complex',   ward: 'H/E', agency: 'IITM', lat: 19.0535, lon: 72.8464 }),
  withPoll({ id: 'deonar',     name: 'Deonar',                  ward: 'M/E', agency: 'IITM', lat: 19.0495, lon: 72.9230 }),
  withPoll({ id: 'borivali',   name: 'Borivali East',           ward: 'R/N', agency: 'IITM', lat: 19.2324, lon: 72.8690 }),
  withPoll({ id: 'kandivali',  name: 'Kandivali West',          ward: 'R/S', agency: 'BMC',  lat: 19.2159, lon: 72.8317 }),
  withPoll({ id: 'colaba',     name: 'Navy Nagar Colaba',       ward: 'A',   agency: 'IITM', lat: 18.8978, lon: 72.8133 }),
];



/* ── Mock fallback data (used when backend is offline) ───────────── */
export function createMockForecast(baseAqi) {
  const now = new Date();
  return Array.from({ length: 24 }, (_, i) => {
    const h = (now.getHours() + i) % 24;
    const diurnal = Math.sin(((h - 14) / 24) * Math.PI * 2) * 0.22;
    const noise   = (Math.random() - 0.5) * 0.10;
    const aqi     = Math.max(15, Math.round(baseAqi * (1 + diurnal + noise)));
    return {
      timestamp:  new Date(now.getTime() + i * 3_600_000).toISOString(),
      aqi,
      aqi_lower:  Math.max(0, Math.round(aqi * 0.83)),
      aqi_upper:  Math.round(aqi * 1.17),
    };
  });
}

const ATTR_EXPLANATIONS = {
  'Good':         'Air quality is good today. Light sea breeze is diluting any local sources. Safe for all activities.',
  'Satisfactory': 'Mild traffic emissions and some dust. Sensitive individuals may notice slight irritation during heavy exertion.',
  'Moderate':     'Traffic from arterial roads and construction dust are the primary contributors. Stagnant afternoon air reduces dispersion.',
  'Poor':         'Heavy traffic, industrial activity and weak winds are combining to trap pollutants. Limit prolonged outdoor exertion.',
  'Very Poor':    'Multiple urban sources — dense traffic, dust and low wind — are driving elevated levels. Avoid outdoor activity if possible.',
  'Severe':       'Stagnant air conditions are trapping pollutants from traffic and industrial sources. Health risk for everyone outdoors.',
};

export function createMockAttribution(station) {
  const cat    = getCategory(station.aqi);
  const speed  = +(1.5 + Math.random() * 3.5).toFixed(1);
  const deg    = Math.round(150 + Math.random() * 120);
  const compass = deg < 180 ? 'SSW' : deg < 225 ? 'SW' : 'WSW';
  return {
    explanation: ATTR_EXPLANATIONS[cat.label] ?? ATTR_EXPLANATIONS['Moderate'],
    wind:  { speed_mps: speed, direction_deg: deg, compass },
    fires: [],
    news:  [],
  };
}
