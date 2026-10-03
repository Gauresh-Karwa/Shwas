/**
 * TimeSlider.jsx
 *
 * Positioned bottom-left of the map.
 * Offset 0 = Now (live station readings).
 * Offset 1-23 = Forecast +Nh, using pre-fetched SARIMA data.
 */
import React from 'react';
import './TimeSlider.css';

export default function TimeSlider({ offset, onChange, hasForecasts }) {
  const now  = new Date();
  const at   = new Date(now.getTime() + offset * 3_600_000);
  const time = at.toLocaleTimeString('en-IN', {
    hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
  });

  const isNow  = offset === 0;
  const label  = isNow ? 'Now \u2014 live readings' : `Forecast +${offset}h \u00b7 ${time}`;
  const pct    = ((offset / 23) * 100).toFixed(2);
  const fillBg = `linear-gradient(to right, var(--green) ${pct}%, var(--border) ${pct}%)`;

  return (
    <div className="ts-card" role="group" aria-label="Forecast time slider">
      {/* Label row */}
      <div className="ts-header">
        <span className="ts-icon" aria-hidden="true">
          {/* Clock SVG — no emoji */}
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
        </span>
        <span
          className={`ts-label${isNow ? ' ts-label--now' : ''}`}
          aria-live="polite"
        >
          {label}
        </span>
      </div>

      {/* Slider row */}
      <div className="ts-track">
        <span className="ts-end">Now</span>
        <input
          id="time-slider"
          type="range"
          className="ts-input"
          min={0} max={23} step={1}
          value={offset}
          disabled={!hasForecasts}
          onChange={e => onChange(+e.target.value)}
          aria-label="Forecast offset in hours"
          aria-valuetext={label}
          style={{ background: fillBg }}
        />
        <span className="ts-end">+24h</span>
      </div>

      {/* Hour ticks */}
      <div className="ts-ticks" aria-hidden="true">
        {[6, 12, 18].map(h => (
          <span key={h} className={`ts-tick${h === offset ? ' ts-tick--active' : ''}`}
            style={{ left: `${(h / 23 * 100).toFixed(1)}%` }}>
            {h === 0 ? '' : `+${h}h`}
          </span>
        ))}
      </div>

      {/* Loading indicator */}
      {!hasForecasts && (
        <div className="ts-loading" aria-live="polite">
          Loading forecasts for all stations…
        </div>
      )}
    </div>
  );
}
