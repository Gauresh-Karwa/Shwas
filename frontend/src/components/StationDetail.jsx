import React from 'react';
import { getCategory } from '../utils/aqi';
import './StationDetail.css';

// currentOffset (0–23): slider position — draws a vertical marker in the chart.
function ForecastChart({ forecasts, currentOffset }) {
  if (!forecasts?.length) return null;
  const isAllZero = forecasts.every(f => f.aqi === 0);
  if (isAllZero) {
    return <div style={{ padding: '20px 0', color: 'var(--sage)', fontSize: '0.85rem' }}>Insufficient historical data for forecast.</div>;
  }

  const W = 300, H = 80;
  const n = forecasts.length;

  const lowers = forecasts.map(f => f.aqi_lower ?? f.aqi);
  const uppers = forecasts.map(f => f.aqi_upper ?? f.aqi);
  const center = forecasts.map(f => f.aqi);

  const minV = Math.min(...lowers) * 0.92;
  const maxV = Math.max(...uppers) * 1.06;
  const range = Math.max(maxV - minV, 1);

  const px = i => +((i / (n - 1)) * W).toFixed(2);
  const py = v => +((H - ((v - minV) / range) * H)).toFixed(2);

  const peakAqi = Math.max(...center);
  const lowAqi = Math.min(...center);

  // Band (upper → lower reversed)
  const bandUp = forecasts.map((f, i) => `${i === 0 ? 'M' : 'L'}${px(i)},${py(f.aqi_upper ?? f.aqi)}`).join('');
  const bandDn = [...forecasts].reverse().map((f, i) => `L${px(n - 1 - i)},${py(f.aqi_lower ?? f.aqi)}`).join('');

  // Center line
  const line = forecasts.map((f, i) => `${i === 0 ? 'M' : 'L'}${px(i)},${py(f.aqi)}`).join('');

  // Axis ticks every 6 hours
  const tickIdxs = [0, 6, 12, 18, n - 1].filter(i => i < n);

  const fmtTick = ts => {
    try {
      return new Date(ts).toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit', hour12: false,
        timeZone: 'Asia/Kolkata',
      });
    } catch { return ''; }
  };

  return (
    <div style={{ paddingBottom: 4 }}>
      <div className="fc-meta">Peak {peakAqi}, low {lowAqi}</div>
      <svg
        className="fc-svg"
        viewBox={`0 0 ${W} ${H + 20}`}
        aria-label="24-hour AQI forecast"
        role="img"
      >
        {/* Confidence band */}
        <path d={`${bandUp}${bandDn}Z`} fill="var(--light-sage)" opacity="0.8" />

        {/* Centre line */}
        <path
          d={line}
          fill="none"
          stroke="var(--green)"
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Current-position dot */}
        <circle cx={px(0)} cy={py(forecasts[0].aqi)} r="3.5" fill="var(--forest)" />

        {/* Time labels */}
        {tickIdxs.map(i => (
          <text
            key={i}
            x={px(i)}
            y={H + 14}
            textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
            fontSize="9"
            fill="var(--muted)"
            fontFamily="Inter, sans-serif"
          >
            {fmtTick(forecasts[i]?.timestamp)}
          </text>
        ))}

        {/* Slider position marker */}
        {currentOffset != null && currentOffset > 0 && currentOffset < n && (() => {
          const mX = px(currentOffset);
          const mY = py(forecasts[currentOffset].aqi);
          return (
            <g key="slider-marker">
              {/* Vertical dashed rule */}
              <line
                x1={mX} y1={0} x2={mX} y2={H}
                stroke="var(--forest)" strokeWidth="1"
                strokeDasharray="3 2" opacity="0.45"
              />
              {/* Filled dot at AQI level */}
              <circle
                cx={mX} cy={mY} r="4"
                fill="var(--forest)" stroke="var(--white)" strokeWidth="1.5"
              />
            </g>
          );
        })()}
      </svg>
    </div>
  );
}

// ── Attribution card ──────────────────────────────────────────────
function AttributionCard({ data, loading }) {
  if (loading) {
    return (
      <div className="sdc__attr attr-skeleton">
        <span className="skeleton" style={{ width: 160, height: 16, marginBottom: 10 }} />
        <span className="skeleton" style={{ width: '100%', height: 13, marginBottom: 6 }} />
        <span className="skeleton" style={{ width: '80%', height: 13, marginBottom: 12 }} />
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {[80, 65, 72].map((w, i) => (
            <span key={i} className="skeleton" style={{ width: w, height: 24, borderRadius: 99 }} />
          ))}
        </div>
      </div>
    );
  }

  if (!data) return null;

  const { explanation, wind, fires } = data;

  // Build factor tags from structured data
  const factors = [];
  if (fires?.length) factors.push('Fire smoke');
  if (wind?.speed_mps != null) factors.push(`${wind.compass ?? 'Wind'} wind`);
  factors.push('Traffic');

  // Build data pills
  const pills = [];
  if (wind?.speed_mps != null && wind?.direction_deg != null) {
    pills.push(`Wind ${wind.speed_mps.toFixed(1)} m/s from ${wind.direction_deg}°`);
  }
  if (fires?.length) {
    pills.push(`Fire ${fires[0].distance_km} km away`);
  }

  return (
    <div className="sdc__attr">
      <h4 className="attr-title">Why is the air bad here?</h4>
      <p className="attr-text">{explanation}</p>
      {factors.length > 0 && (
        <div className="attr-tags">
          {factors.map(f => <span key={f} className="attr-tag">{f}</span>)}
        </div>
      )}
      {pills.length > 0 && (
        <div className="attr-pills">
          {pills.map(p => <span key={p} className="attr-pill">{p}</span>)}
        </div>
      )}
    </div>
  );
}

// ── Station detail card ───────────────────────────────────────────
export function StationDetailCard({ station, forecast, forecastLoading, attribution, attributionLoading, forecastOffset }) {
  if (!station) return null;

  const cat = getCategory(station.aqi);

  return (
    <div className="sdc">
      {/* Header */}
      <div className="sdc__head">
        <div>
          <div className="sdc__name">{station.name}</div>
          <div className="sdc__sub">
            Ward {station.ward} · {cat.label}, AQI {station.aqi}
          </div>
        </div>
        <span
          className="sdc__aqi-badge"
          style={{ background: cat.color }}
          aria-label={`AQI ${station.aqi}`}
        >
          {station.aqi}
        </span>
      </div>

      {/* Pollutant grid */}
      <div className="sdc__pollutants" aria-label="Pollutant concentrations">
        {[
          { key: 'pm25', label: 'PM2.5' },
          { key: 'pm10', label: 'PM10' },
          { key: 'no2', label: 'NO₂' },
          { key: 'so2', label: 'SO₂' },
        ].map(({ key, label }) => (
          <div key={key} className="sdc__poll-cell">
            <div className="sdc__poll-val">{station[key] ?? '—'}</div>
            <div className="sdc__poll-name">{label}</div>
            <div className="sdc__poll-unit">μg/m³</div>
          </div>
        ))}
      </div>

      {/* Forecast */}
      <div className="sdc__forecast">
        <div className="sdc__sect-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          Next 24 hours
          <span style={{
            fontSize: 10, fontWeight: 600, padding: '1px 7px',
            borderRadius: 99, background: 'var(--light-sage)',
            color: 'var(--forest)', border: '1px solid var(--sage)',
          }}>SARIMAX · weather-aware</span>
        </div>
        {forecastLoading ? (
          <span className="skeleton" style={{ width: '100%', height: 80, marginBottom: 8, display: 'block' }} />
        ) : (
          <ForecastChart forecasts={forecast} currentOffset={forecastOffset} />
        )}
      </div>

      {/* Attribution */}
      <AttributionCard data={attribution} loading={attributionLoading} />
    </div>
  );
}

// ── Click-to-estimate card ────────────────────────────────────────
export function EstimateCard({ estimate, onClose }) {
  if (!estimate) return null;

  const { lat, lon, estimated_aqi, model, stations_used, uncertainty_std } = estimate;
  const aqi = Math.round(estimated_aqi ?? 0);
  const cat = getCategory(aqi);
  const uncert = uncertainty_std != null ? Math.round(uncertainty_std) : null;

  return (
    <div className="est-card">
      <div className="est-card__head">
        <span className="est-card__title">Estimated air quality here</span>
        <button
          className="est-card__close"
          onClick={onClose}
          aria-label="Close estimate"
        >
          {/* × character — not an emoji */}
          &#215;
        </button>
      </div>

      <div className="est-card__body">
        <div className="est-card__coord">
          {lat?.toFixed(4)}° N, {lon?.toFixed(4)}° E
        </div>

        <div className="est-card__aqi-row">
          <span className="est-card__aqi-num" style={{ color: cat.color }}>
            {aqi}
          </span>
          {uncert != null && (
            <span style={{
              fontSize: 12, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums',
              alignSelf: 'flex-end', paddingBottom: 4,
            }}>± {uncert}</span>
          )}
          <span className="est-card__cat" style={{ background: cat.color }}>
            {cat.label}
          </span>
        </div>

        <p className="est-card__disclaimer">
          No sensor at this location. Estimated by the spatial model using nearby station readings.
        </p>

        <div className="est-card__meta">
          <div className="est-card__meta-row">
            <span className="est-card__meta-key">Model used</span>
            <span className="est-card__model-badge">{(model ?? 'IDW').toUpperCase()}</span>
          </div>
          {stations_used != null && (
            <div className="est-card__meta-row">
              <span className="est-card__meta-key">Based on</span>
              <span className="est-card__meta-val">{stations_used} stations</span>
            </div>
          )}
          {uncert != null && (
            <div className="est-card__meta-row">
              <span className="est-card__meta-key">95% CI</span>
              <span className="est-card__meta-val">{aqi - uncert * 2}–{aqi + uncert * 2} AQI</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}