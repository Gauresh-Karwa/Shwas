export const CATS = [
  { label: 'Good',         min: 0,   max: 50,  color: '#3E9C78' },
  { label: 'Satisfactory', min: 51,  max: 100, color: '#A3B94F' },
  { label: 'Moderate',     min: 101, max: 200, color: '#E0B341' },
  { label: 'Poor',         min: 201, max: 300, color: '#E08A3C' },
  { label: 'Very Poor',    min: 301, max: 400, color: '#C4483F' },
  { label: 'Severe',       min: 401, max: 500, color: '#7A2E3A' },
];

export function getCategory(aqi) {
  if (aqi == null) return { label: 'No data', min: 0, max: 500, color: '#D5E3DA' };
  for (const c of CATS) if (aqi <= c.max) return c;
  return CATS[CATS.length - 1];
}

export function getAQIColor(aqi) {
  return getCategory(aqi).color;
}
