/**
 * PollutantBars.jsx
 *
 * Shows how much of each pollutant is in the air, as bars.
 * Bar length = the pollutant's CPCB sub-index (how close it is to unhealthy),
 * so the longest bar is the pollutant that sets the AQI.
 * Works for a real station and for an estimated map point.
 *
 * Props:
 *   readings  { pm25, pm10, no2, so2 }  values in ug/m3 (null = no data)
 *   note      optional small print under the bars
 */
import React from 'react';
import { CATS, subIndex, getAQIColor } from '../utils/aqi';
import './PollutantsBars.css';

const ITEMS = [
  { key: 'pm25', id: 'PM2.5', label: 'PM2.5' },
  { key: 'pm10', id: 'PM10', label: 'PM10' },
  { key: 'no2', id: 'NO2', label: 'NO\u2082' },
  { key: 'so2', id: 'SO2', label: 'SO\u2082' },
];

const SCALE_MAX = 300; // bar is full at a sub-index of 300 (top of "Poor")

// Faint category colours behind each bar, same bands as the forecast chart
const TRACK_BG = (() => {
  const stops = [];
  CATS.filter(c => c.max <= SCALE_MAX).forEach((c, i, arr) => {
    const lo = i === 0 ? 0 : arr[i - 1].max;
    stops.push(`${c.color}2e ${(lo / SCALE_MAX) * 100}%`, `${c.color}2e ${(c.max / SCALE_MAX) * 100}%`);
  });
  return `linear-gradient(to right, ${stops.join(', ')})`;
})();

export default function PollutantBars({ readings, note }) {
  const rows = ITEMS.map(it => {
    const v = readings?.[it.key];
    return { ...it, v, idx: v != null ? subIndex(it.id, v) : null };
  });
  const have = rows.filter(r => r.idx != null);

  if (!have.length) {
    return <p className="pb__empty">No pollutant readings are available here right now.</p>;
  }
  const lead = have.reduce((a, b) => (b.idx > a.idx ? b : a));

  return (
    <section className="pb" aria-label="Pollutant levels">
      <h3 className="pb__title">What is in the air</h3>
      {rows.map(r => (
        <div className="pb__row" key={r.key}>
          <span className="pb__name">
            {r.label}
            {r === lead && have.length > 1 && <span className="pb__lead">main driver</span>}
          </span>
          <span className="pb__track" style={{ background: TRACK_BG }}>
            {r.idx != null && (
              <span
                className="pb__fill"
                style={{ width: `${Math.max(3, Math.min(100, (r.idx / SCALE_MAX) * 100))}%`, background: getAQIColor(r.idx) }}
              />
            )}
          </span>
          <span className="pb__val">
            {r.v != null ? r.v : '\u2014'}
            <small>{'\u00b5g/m\u00b3'}</small>
          </span>
        </div>
      ))}
      <p className="pb__note">
        A longer bar means closer to unhealthy levels.{note ? ` ${note}` : ''}
      </p>
    </section>
  );
}