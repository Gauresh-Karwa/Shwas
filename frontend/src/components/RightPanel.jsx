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
import { describeAirMass } from '../utils/airMass';
import './RightPanel.css';
import './StationDetail.css';
import ForecastChart24 from './ForecastChart24';
import ExplainCard from './ExplainCard';
import PollutantBars from './PollutantsBars';

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


// ── Source apportionment pill ────────────────────────────────────────
function SourceTag({ pm25, pm10 }) {
  if (pm25 == null || pm10 == null || pm10 === 0) return null;
  const ratio = Math.min(pm25 / pm10, 1.0);
  let label, color;
  if (ratio >= 0.60) { label = `Fine-fraction ${ratio.toFixed(2)} · Combustion / vehicular`; color = '#E08A3C'; }
  else if (ratio <= 0.35) { label = `Fine-fraction ${ratio.toFixed(2)} · Dust dominated`; color = '#A3B94F'; }
  else { label = `Fine-fraction ${ratio.toFixed(2)} · Mixed profile`; color = '#E0B341'; }
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

// ── Pollutant levels (bars) + source tag ─────────────────────────────
function PollutantGrid({ station, note }) {
  return (
    <>
      <PollutantBars readings={station} note={note} />
      <SourceTag pm25={station.pm25} pm10={station.pm10} />
    </>
  );
}

// ── Loading skeleton ────────────────────────────────────────────────
function Skeleton() {
  return (
    <div className="rp-skeleton" aria-busy="true" aria-label="Loading attribution">
      <span className="skeleton" style={{ width: '90%', height: 14, marginBottom: 8 }} />
      <span className="skeleton" style={{ width: '100%', height: 14, marginBottom: 8 }} />
      <span className="skeleton" style={{ width: '75%', height: 14, marginBottom: 20 }} />
      <span className="skeleton" style={{ width: 120, height: 12, marginBottom: 12 }} />
      <span className="skeleton" style={{ width: '60%', height: 12, marginBottom: 12 }} />
      <span className="skeleton" style={{ width: '50%', height: 12, marginBottom: 20 }} />
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
  pointPollutants,   // estimated pollutants for a clicked point | null
  attribution,       // real API data | null
  loading,
  error,
  onRetry,
  forecast,
  forecastLoading,
  forecastOffset,
}) {
  const isOpen = !!(selectedContext || loading || error);

  const aqi = selectedContext?.aqi ?? 0;
  const airPath = describeAirMass(attribution?.air_mass);
  const cat = getCategory(aqi);
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

        {/* 24-hour forecast: always shown for any station or clicked point */}
        {selectedContext && (
          <ForecastChart24
            forecast={forecast}
            loading={forecastLoading}
            nowAqi={aqi}
          />
        )}

        {/* Station pollutant grid (only when the station has readings) */}
        {selectedStation && (
          <>
            {['pm25', 'pm10', 'no2', 'so2'].some(k => selectedStation[k] != null)
              ? <PollutantGrid station={selectedStation} />
              : <p className="rp-muted" style={{ padding: '0 var(--s2) 8px', fontSize: 12 }}>
                No pollutant readings available for this station right now.
              </p>}
            <div className="rp-divider" />
          </>
        )}

        {/* Clicked point (no station): pollutants estimated from nearby stations */}
        {!selectedStation && selectedContext && (
          <>
            {pointPollutants
              ? <PollutantGrid
                station={pointPollutants}
                note={`Estimated from the ${pointPollutants.used} nearest station${pointPollutants.used > 1 ? 's' : ''}. There is no sensor at this spot.`}
              />
              : <p className="rp-muted" style={{ padding: '0 var(--s2) 8px', fontSize: 12 }}>
                No pollutant readings from nearby stations right now, so levels can&apos;t be estimated here.
              </p>}
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
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <p className="rp-error__msg">Explanation is unavailable right now.</p>
            <button className="rp-retry" onClick={onRetry}>Try again</button>
          </div>
        )}

        {/* Attribution: data */}
        {attribution && !loading && !error && (
          <>
            {/* Plain-English explanation */}
            <ExplainCard text={attribution.explanation} aqi={aqi} />
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

            {/* Air path row (back-trajectory) */}
            {airPath && (
              <div className="rp-row">
                <div className="rp-row__icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                    stroke="#1D5C8C" strokeWidth="2"
                    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="5" cy="18" r="2" />
                    <circle cx="19" cy="6" r="2" />
                    <path d="M7 17c4-1 3-5 6-6s4-2 4-3" strokeDasharray="2 3" />
                  </svg>
                </div>
                <div className="rp-row__body">
                  <div className="rp-row__label">Where this air came from</div>
                  <div className="rp-row__val"><strong>{airPath.headline}</strong></div>
                  {airPath.detail && <div className="rp-row__sub">{airPath.detail}</div>}
                </div>
              </div>
            )}

            {/* Fires row */}
            <div className="rp-row">
              <div className="rp-row__icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                  stroke="var(--sage)" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round">
                  <path d="M8.5 14.5A3.5 3.5 0 0 0 12 18a3.5 3.5 0 0 0 3.5-3.5c0-2-1.5-4-3.5-7-2 3-3.5 5-3.5 7z" />
                  <path d="M12 11c0-2 1.5-3.5 3-5" />
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
                            {f.frp_mw != null && ` · ${Number(f.frp_mw).toFixed(1)} MW`}
                          </span>
                          {f.upwind === true && <span className="rp-fire-tag">upwind</span>}
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
                      {item.domain && (
                        <span className="rp-news-item__source">{item.domain}</span>
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