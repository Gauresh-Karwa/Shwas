/**
 * RightPanel.jsx
 * Attribution + station detail panel.
 * Slides in when a station or click-point is selected.
 *
 * Shows real API data only — never renders mock text as real.
 * On error: "Explanation is unavailable right now" + Retry button.
 */
import React from 'react';
import { getCategory } from '../utils/aqi';
import './RightPanel.css';
import './StationDetail.css';

// ── Compass helper ───────────────────────────────────────────────────
const COMPASS_LABELS = [
  'north', 'north-east', 'east', 'south-east',
  'south', 'south-west', 'west', 'north-west',
];
function compassWords(deg) {
  if (deg == null) return null;
  const idx = Math.round(((deg % 360) + 360) % 360 / 45) % 8;
  return COMPASS_LABELS[idx];
}

// ── Wind arrow icon (inline SVG, rotated to wind direction) ─────────
function WindArrowIcon({ deg }) {
  const rotate = (deg ?? 0) + 180; // Arrow points INTO wind
  return (
    <svg className="rp-wind-icon" width="20" height="20"
      viewBox="0 0 24 24" aria-hidden="true"
      style={{ transform: `rotate(${rotate}deg)` }}>
      <path d="M12 3 L12 21 M12 3 L7 10 M12 3 L17 10"
        stroke="var(--sage)" strokeWidth="2.2"
        strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

// ── Forecast line chart (SVG, self-written) ──────────────────────────
function ForecastChart({ forecasts, currentOffset }) {
  if (!forecasts?.length) return null;

  const W = 290, H = 76;
  const n = forecasts.length;

  const lowers = forecasts.map(f => f.aqi_lower ?? f.aqi);
  const uppers = forecasts.map(f => f.aqi_upper ?? f.aqi);
  const center = forecasts.map(f => f.aqi);

  const minV  = Math.min(...lowers) * 0.92;
  const maxV  = Math.max(...uppers) * 1.06;
  const range = Math.max(maxV - minV, 1);

  const px = i => +((i / (n - 1)) * W).toFixed(2);
  const py = v => +((H - ((v - minV) / range) * H)).toFixed(2);

  const peakAqi = Math.max(...center);
  const lowAqi  = Math.min(...center);

  const bandUp = forecasts.map((f, i) =>
    `${i === 0 ? 'M' : 'L'}${px(i)},${py(f.aqi_upper ?? f.aqi)}`).join('');
  const bandDn = [...forecasts].reverse().map((f, i) =>
    `L${px(n - 1 - i)},${py(f.aqi_lower ?? f.aqi)}`).join('');
  const line = forecasts.map((f, i) =>
    `${i === 0 ? 'M' : 'L'}${px(i)},${py(f.aqi)}`).join('');

  const tickIdxs = [0, 6, 12, 18, n - 1].filter(i => i < n);
  const fmtTick  = ts => {
    try {
      return new Date(ts).toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata',
      });
    } catch { return ''; }
  };

  return (
    <div className="rp-chart">
      <div className="rp-chart__meta">Peak {peakAqi}, low {lowAqi}</div>
      <svg className="fc-svg" viewBox={`0 0 ${W} ${H + 20}`}
        aria-label="24-hour AQI forecast" role="img">
        {/* Confidence band */}
        <path d={`${bandUp}${bandDn}Z`} fill="var(--light-sage)" opacity="0.8" />
        {/* Centre line — forest green */}
        <path d={line} fill="none" stroke="var(--green)"
          strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* Now dot */}
        <circle cx={px(0)} cy={py(forecasts[0].aqi)} r="3.5" fill="var(--forest)" />
        {/* Slider position marker */}
        {currentOffset > 0 && currentOffset < n && (() => {
          const mX = px(currentOffset);
          const mY = py(forecasts[currentOffset]?.aqi ?? forecasts[0].aqi);
          return (
            <g>
              <line x1={mX} y1={0} x2={mX} y2={H}
                stroke="var(--forest)" strokeWidth="1"
                strokeDasharray="3 2" opacity="0.45" />
              <circle cx={mX} cy={mY} r="4"
                fill="var(--forest)" stroke="var(--white)" strokeWidth="1.5" />
            </g>
          );
        })()}
        {/* Time labels */}
        {tickIdxs.map(i => (
          <text key={i} x={px(i)} y={H + 14}
            textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
            fontSize="9" fill="var(--muted)" fontFamily="Inter, sans-serif">
            {fmtTick(forecasts[i]?.timestamp)}
          </text>
        ))}
      </svg>
    </div>
  );
}

// ── Source apportionment pill ────────────────────────────────────────
function SourceTag({ pm25, pm10 }) {
  if (pm25 == null || pm10 == null || pm10 === 0) return null;
  const ratio = Math.min(pm25 / pm10, 1.0);
  let label, color;
  if (ratio >= 0.60)      { label = `Fine-fraction ${ratio.toFixed(2)} · Combustion / vehicular`; color = '#E08A3C'; }
  else if (ratio <= 0.35) { label = `Fine-fraction ${ratio.toFixed(2)} · Dust dominated`;          color = '#A3B94F'; }
  else                    { label = `Fine-fraction ${ratio.toFixed(2)} · Mixed profile`;            color = '#E0B341'; }
  return (
    <div style={{
      margin: '4px var(--s2) 0',
      padding: '3px 10px',
      borderRadius: 99,
      background: color + '22',
      border: `1px solid ${color}44`,
      fontSize: 11,
      color,
      fontWeight: 600,
      display: 'inline-block',
    }}>{label}</div>
  );
}

// ── Pollutant grid ───────────────────────────────────────────────────
function PollutantGrid({ station }) {
  const items = [
    { key: 'pm25', label: 'PM2.5' },
    { key: 'pm10', label: 'PM10'  },
    { key: 'no2',  label: 'NO₂'   },
    { key: 'so2',  label: 'SO₂'   },
  ];
  return (
    <>
      <div className="sdc__pollutants" aria-label="Pollutant concentrations">
        {items.map(({ key, label }) => (
          <div key={key} className="sdc__poll-cell">
            <div className="sdc__poll-val">{station[key] ?? '—'}</div>
            <div className="sdc__poll-name">{label}</div>
            <div className="sdc__poll-unit">μg/m³</div>
          </div>
        ))}
      </div>
      <SourceTag pm25={station.pm25} pm10={station.pm10} />
    </>
  );
}

// ── Loading skeleton ────────────────────────────────────────────────
function Skeleton() {
  return (
    <div className="rp-skeleton" aria-busy="true" aria-label="Loading attribution">
      <span className="skeleton" style={{ width: '90%',  height: 14, marginBottom: 8 }} />
      <span className="skeleton" style={{ width: '100%', height: 14, marginBottom: 8 }} />
      <span className="skeleton" style={{ width: '75%',  height: 14, marginBottom: 20 }} />
      <span className="skeleton" style={{ width: 120,    height: 12, marginBottom: 12 }} />
      <span className="skeleton" style={{ width: '60%',  height: 12, marginBottom: 12 }} />
      <span className="skeleton" style={{ width: '50%',  height: 12, marginBottom: 20 }} />
      {[1, 2, 3].map(i => (
        <span key={i} className="skeleton" style={{ width: '85%', height: 13, marginBottom: 8 }} />
      ))}
    </div>
  );
}

// ── Main exported panel ─────────────────────────────────────────────
export default function RightPanel({
  selectedStation,   // full station object (has pollutants) | null
  selectedContext,   // { name, lat, lon, aqi } — station or clicked point
  attribution,       // real API data | null
  loading,
  error,
  onRetry,
  forecast,
  forecastLoading,
  forecastOffset,
}) {
  const isOpen = !!(selectedContext || loading || error);

  const aqi  = selectedContext?.aqi ?? 0;
  const cat  = getCategory(aqi);
  const name = selectedContext?.name ?? null;

  const fmtTime = iso => {
    try {
      return new Date(iso ?? Date.now()).toLocaleTimeString('en-IN', {
        hour: '2-digit', minute: '2-digit', hour12: true, timeZone: 'Asia/Kolkata',
      });
    } catch { return ''; }
  };

  return (
    <aside className={`right-panel${isOpen ? ' right-panel--open' : ''}`}
      aria-label="Air quality attribution">

      {/* Header */}
      <div className="rp-head">
        <div>
          <h2 className="rp-title">
            Why is the air{' '}
            <span style={{ color: cat.color }}>{cat.label.toLowerCase()} (AQI {aqi})</span>
            {' '}here?
          </h2>
          {name && <div className="rp-subtitle">{name}</div>}
        </div>
        {attribution?.fetched_at && (
          <span className="rp-updated">Updated {fmtTime(attribution.fetched_at)}</span>
        )}
      </div>

      <div className="rp-body">

        {/* Station pollutant grid + forecast chart */}
        {selectedStation && (
          <>
            <PollutantGrid station={selectedStation} />
            <div className="rp-sect-label section-label" style={{ padding: '0 var(--s2) 6px', display: 'flex', alignItems: 'center', gap: 6 }}>
              Next 24 hours
              <span style={{
                fontSize: 10, fontWeight: 600, padding: '1px 7px',
                borderRadius: 99, background: 'var(--light-sage)',
                color: 'var(--forest)', border: '1px solid var(--sage)',
              }}>SARIMAX · weather-aware</span>
            </div>
            {forecastLoading ? (
              <span className="skeleton"
                style={{ width: 'calc(100% - 32px)', height: 76, margin: '0 var(--s2) 12px', display: 'block' }} />
            ) : (
              <div style={{ padding: '0 var(--s2) 8px' }}>
                <ForecastChart forecasts={forecast} currentOffset={forecastOffset} />
              </div>
            )}
            <div className="rp-divider" />
          </>
        )}

        {/* Attribution: loading */}
        {loading && <Skeleton />}

        {/* Attribution: error */}
        {error && !loading && (
          <div className="rp-error" role="alert">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
              stroke="var(--border)" strokeWidth="1.5" strokeLinecap="round"
              style={{ marginBottom: 10 }}>
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <p className="rp-error__msg">Explanation is unavailable right now.</p>
            <button className="rp-retry" onClick={onRetry}>Try again</button>
          </div>
        )}

        {/* Attribution: data */}
        {attribution && !loading && !error && (
          <>
            {/* Plain-English explanation — green left border */}
            <div className="rp-explanation" aria-label="Plain-English explanation">
              {attribution.explanation}
            </div>

            <div className="rp-divider" />

            {/* Wind row */}
            <div className="rp-row">
              <div className="rp-row__icon">
                <WindArrowIcon deg={attribution.wind?.direction_deg} />
              </div>
              <div className="rp-row__body">
                <div className="rp-row__label">Wind</div>
                {attribution.wind ? (
                  <div className="rp-row__val">
                    <strong>{attribution.wind.speed_mps?.toFixed(1)} m/s</strong>
                    {' '}from the{' '}
                    {compassWords(attribution.wind.direction_deg) ?? attribution.wind.compass}
                  </div>
                ) : (
                  <div className="rp-row__val rp-muted">No wind data</div>
                )}
              </div>
            </div>

            {/* Fires row */}
            <div className="rp-row">
              <div className="rp-row__icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                  stroke="var(--sage)" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round">
                  <path d="M8.5 14.5A3.5 3.5 0 0 0 12 18a3.5 3.5 0 0 0 3.5-3.5c0-2-1.5-4-3.5-7-2 3-3.5 5-3.5 7z"/>
                  <path d="M12 11c0-2 1.5-3.5 3-5"/>
                </svg>
              </div>
              <div className="rp-row__body">
                <div className="rp-row__label">Active fires</div>
                {attribution.fires?.length > 0 ? (
                  <>
                    <div className="rp-row__val">
                      <strong>{attribution.fires.length}</strong> detected nearby
                    </div>
                    <div className="rp-fires-list">
                      {attribution.fires.slice(0, 3).map((f, i) => (
                        <div key={i} className="rp-fire-item">
                          <span className="rp-fire-dot" />
                          <span>
                            {f.distance_km != null ? `${f.distance_km} km away` : 'Nearby'}
                            {f.intensity_mw != null && ` · ${f.intensity_mw} MW`}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="rp-row__val rp-muted">No active fires detected nearby</div>
                )}
              </div>
            </div>

            {/* News */}
            {attribution.news?.length > 0 && (
              <>
                <div className="rp-divider" />
                <div className="rp-news">
                  <div className="rp-news__label section-label">Related news</div>
                  {attribution.news.slice(0, 3).map((item, i) => (
                    <a key={i} href={item.url} target="_blank" rel="noopener noreferrer"
                      className="rp-news-item">
                      <span className="rp-news-item__title">{item.title}</span>
                      {item.source && (
                        <span className="rp-news-item__source">{item.source}</span>
                      )}
                    </a>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
