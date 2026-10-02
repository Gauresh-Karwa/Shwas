import React, { useState, useRef, useEffect } from 'react';
import './LeftPanel.css';
import { getCategory, CATS } from '../utils/aqi';
import { EstimateCard } from './StationDetail';
import './StationDetail.css';

// ─────────────────────────────────────────────────────────
// Search box — searches the live stations prop
// ─────────────────────────────────────────────────────────
function SearchBox({ stations, onSelect }) {
  const [q, setQ]       = useState('');
  const [open, setOpen] = useState(false);
  const wrapRef         = useRef(null);

  const results = q.trim()
    ? (stations ?? []).filter(s =>
        s.name.toLowerCase().includes(q.toLowerCase()) ||
        String(s.ward).toLowerCase().includes(q.toLowerCase())
      ).slice(0, 6)
    : [];

  useEffect(() => {
    const h = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  return (
    <div className="search" ref={wrapRef}>
      <div className="search__inner">
        <svg className="search__icon" width="14" height="14" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
          <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
        </svg>
        <input
          id="station-search" type="search" className="search__input"
          placeholder="Search stations or wards…" value={q} autoComplete="off"
          aria-label="Search stations and wards"
          onChange={e => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
      </div>
      {open && q.trim() && (
        <div className="search__results" role="listbox" aria-label="Search results">
          {results.length > 0
            ? results.map(s => {
                const cat = getCategory(s.aqi);
                return (
                  <button key={s.id} className="search__result" role="option"
                    onClick={() => { onSelect(s); setQ(''); setOpen(false); }}>
                    <div>
                      <div className="search__result-name">{s.name}</div>
                      <div className="search__result-ward">Ward {s.ward} · {s.agency}</div>
                    </div>
                    <span className="aqi-badge" style={{ background: cat.color }}>{s.aqi}</span>
                  </button>
                );
              })
            : <div className="search__empty">No station matches &ldquo;{q}&rdquo;</div>
          }
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// City AQI card — receives live cityAqi prop
// ─────────────────────────────────────────────────────────
const AQI_DESCRIPTIONS = {
  'Good':         'Air quality is good. Outdoor activities are safe for everyone.',
  'Satisfactory': 'Air is acceptable. Very sensitive people may have mild symptoms.',
  'Moderate':     'Breathing discomfort for sensitive groups and asthma patients.',
  'Poor':         'Breathing discomfort for most people on prolonged outdoor exposure.',
  'Very Poor':    'Respiratory illness likely on prolonged exposure. Limit time outdoors.',
  'Severe':       'Serious risk for everyone. Avoid all outdoor physical exertion.',
};

function CityAQICard({ aqi, loading }) {
  if (loading) {
    return (
      <div className="city-card city-card--loading" style={{ margin: 'var(--s2)' }}>
        <span className="skeleton" style={{ width: 120, height: 11, marginBottom: 12 }} />
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          <span className="skeleton" style={{ width: 80, height: 72 }} />
          <div style={{ flex: 1, paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="skeleton" style={{ width: 80, height: 22 }} />
            <span className="skeleton" style={{ width: '100%', height: 14 }} />
            <span className="skeleton" style={{ width: '80%', height: 14 }} />
          </div>
        </div>
      </div>
    );
  }
  const cat = getCategory(aqi);
  return (
    <div className="city-card fade-up">
      <div className="city-card__label">Mumbai city average</div>
      <div className="city-card__body">
        <div className="city-card__number" style={{ color: cat.color }}>{aqi}</div>
        <div className="city-card__info">
          <span className="city-card__cat" style={{ background: cat.color }}>{cat.label}</span>
          <p className="city-card__desc">{AQI_DESCRIPTIONS[cat.label] ?? ''}</p>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Ward summary cards — live cleanest/worst
// ─────────────────────────────────────────────────────────
function cleanStationName(name) {
  if (!name) return '—';
  // Strip trailing " - AGENCY" pattern (e.g. "Powai, Mumbai - MPCB" → "Powai, Mumbai")
  return name.replace(/\s*-\s*(MPCB|IITM|BMC|CPCB|SAFAR)$/i, '').trim();
}

function WardCards({ cleanest, worst, loading }) {
  if (loading) {
    return (
      <div className="ward-cards">
        {[0, 1].map(i => (
          <div className="ward-card" key={i}>
            <span className="skeleton" style={{ width: 90, height: 10, marginBottom: 8 }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
              <span className="skeleton" style={{ flex: 1, height: 14 }} />
              <span className="skeleton" style={{ width: 36, height: 24, borderRadius: 99 }} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="ward-cards">
      {[
        { label: 'Cleanest station',      icon: '↓', s: cleanest },
        { label: 'Most polluted station', icon: '↑', s: worst    },
      ].map(({ label, icon, s }) => {
        const cat = getCategory(s?.aqi);
        const agency = s?.agency ?? (s?.name?.match(/-\s*(MPCB|IITM|BMC)/i)?.[1] ?? '');
        const displayName = cleanStationName(s?.name);
        return (
          <div className="ward-card" key={label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="ward-card__label" style={{ marginBottom: 2 }}>
                {icon} {label}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="ward-card__name" style={{ fontSize: 12.5 }}>{displayName}</span>
                {agency && (
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: '1px 5px',
                    borderRadius: 3, background: 'var(--border)', color: 'var(--muted)',
                    flexShrink: 0,
                  }}>{agency}</span>
                )}
              </div>
            </div>
            <span className="aqi-badge" style={{ background: cat.color, fontSize: 12, flexShrink: 0 }}>
              {s?.aqi ?? '—'}
            </span>
          </div>
        );
      })}
    </div>
  );
}


// ─────────────────────────────────────────────────────────
// Layer toggles — includes Wind and fires
// ─────────────────────────────────────────────────────────
const LAYERS = [
  { key: 'stations',   label: 'Stations'          },
  { key: 'heatmap',    label: 'Heatmap'           },
  { key: 'boundaries', label: 'Boundaries'        },
  { key: 'population', label: 'Population'        },
  { key: 'slums',      label: 'Slum clusters'     },
  { key: 'windFires',  label: 'Wind and fires'    },
  { key: 'hotspots',   label: 'Hotspots (LCB)'   },
  { key: 'sensors',    label: 'Sensor sites (AI)' },
];

function LayerToggles({ layers, onChange }) {
  return (
    <div className="layers">
      <div className="section-label layers__heading">Map layers</div>
      <div className="layers__grid">
        {LAYERS.map(({ key, label }) => {
          const on = layers[key];
          return (
            <label key={key} className="toggle-row" htmlFor={`toggle-${key}`}>
              <button id={`toggle-${key}`} role="switch" aria-checked={on}
                className="toggle-switch" onClick={() => onChange(key, !on)}
                aria-label={`Toggle ${label} layer`}>
                <span className="toggle-thumb" />
              </button>
              <span className="toggle-label">{label}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Station list — live sorted list
// ─────────────────────────────────────────────────────────
function StationList({ stations, selectedId, onSelect, loading }) {
  const sorted = [...(stations ?? [])].sort((a, b) => b.aqi - a.aqi);

  if (loading) {
    return (
      <div className="station-list">
        <div className="section-label station-list__heading">Stations, worst first</div>
        <div className="station-list__inner">
          {[...Array(6)].map((_, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '9px 10px', gap: 10,
            }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 5 }}>
                <span className="skeleton" style={{ width: '70%', height: 13 }} />
                <span className="skeleton" style={{ width: '45%', height: 11 }} />
              </div>
              <span className="skeleton" style={{ width: 40, height: 24, borderRadius: 99 }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="station-list">
      <div className="section-label station-list__heading">Stations, worst first</div>
      {sorted.length === 0 && <p className="station-list__empty">No stations available.</p>}
      <div className="station-list__inner">
        {sorted.map(s => {
          const cat = getCategory(s.aqi);
          const sel = s.id === selectedId;
          return (
            <button key={s.id} className={`station-row${sel ? ' station-row--selected' : ''}`}
              onClick={() => onSelect(s)} aria-pressed={sel}
              aria-label={`${s.name}, AQI ${s.aqi}, ${cat.label}`}>
              <div className="station-row__left">
                <div className="station-row__name">{s.name}</div>
                <div className="station-row__sub">Ward {s.ward} · {cat.label}</div>
              </div>
              <span className="aqi-badge" style={{ background: cat.color }}>{s.aqi}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Population exposure bar — driven by /api/wards
// ─────────────────────────────────────────────────────────
const POP_CAT_ORDER = ['Good', 'Satisfactory', 'Moderate', 'Poor', 'Very Poor', 'Severe'];
const POP_CAT_COLORS = {
  'Good': '#3E9C78', 'Satisfactory': '#A3B94F', 'Moderate': '#E0B341',
  'Poor': '#E08A3C', 'Very Poor': '#C4483F', 'Severe': '#7A2E3A',
};

function fmtM(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function PopulationExposure({ wardExposure, loading }) {
  if (loading) return (
    <div style={{ margin: 'var(--s2)', marginTop: 0 }}>
      <span className="skeleton" style={{ width: '60%', height: 10, display: 'block', marginBottom: 8 }} />
      <span className="skeleton" style={{ width: '100%', height: 12, display: 'block', borderRadius: 6 }} />
    </div>
  );
  if (!wardExposure) return null;

  const { population_by_category, total_population } = wardExposure;
  if (!total_population) return null;

  // Build ordered segments (only categories that have population)
  const segments = POP_CAT_ORDER
    .filter(cat => (population_by_category?.[cat] ?? 0) > 0)
    .map(cat => ({ cat, pop: population_by_category[cat], color: POP_CAT_COLORS[cat] }));

  return (
    <div style={{ margin: 'var(--s2)', marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 5 }}>
        <span className="section-label" style={{ margin: 0, fontSize: 10 }}>Population exposure</span>
        <span style={{ fontSize: 10, color: 'var(--muted)' }}>{fmtM(total_population)} total</span>
      </div>
      {/* Stacked bar */}
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', gap: 1 }}>
        {segments.map(({ cat, pop, color }) => (
          <div key={cat} title={`${cat}: ${fmtM(pop)}`}
            style={{ flex: pop, background: color, minWidth: 2 }} />
        ))}
      </div>
      {/* Legend pills */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', marginTop: 6 }}>
        {segments.map(({ cat, pop, color }) => (
          <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: 'var(--muted)' }}>
              <strong style={{ color: 'var(--text)' }}>{fmtM(pop)}</strong> {cat}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Legend (exported — rendered inside map area)
// ─────────────────────────────────────────────────────────
const HEALTH_TIPS = {
  'Good':         'Air quality is satisfactory. No restrictions.',
  'Satisfactory': 'Unusually sensitive people should consider reducing prolonged exertion.',
  'Moderate':     'Sensitive groups (elderly, children, respiratory/heart conditions) should reduce prolonged exertion outdoors.',
  'Poor':         'Everyone should reduce prolonged or heavy exertion. Sensitive groups avoid outdoor activity.',
  'Very Poor':    'Everyone should avoid prolonged exertion. Sensitive groups should stay indoors.',
  'Severe':       'Everyone should avoid all outdoor exertion. Sensitive groups should remain indoors and keep windows closed.',
};

export function Legend() {
  const [open, setOpen] = useState(false);

  // Close on click outside
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position: 'absolute', bottom: 20, right: 16, zIndex: 100 }}>
      {/* Collapsed toggle button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Show AQI scale"
          style={{
            display: 'flex', alignItems: 'center', gap: 7,
            background: 'rgba(255,255,255,0.92)',
            backdropFilter: 'blur(12px)',
            border: '1px solid var(--border)',
            borderRadius: 99,
            boxShadow: '0 2px 12px rgba(0,0,0,0.12)',
            padding: '6px 14px 6px 10px',
            cursor: 'pointer',
            fontFamily: 'Inter, sans-serif',
            fontSize: 12, fontWeight: 600, color: 'var(--text)',
            transition: 'box-shadow 0.2s',
          }}
          onMouseEnter={e => e.currentTarget.style.boxShadow = '0 4px 18px rgba(0,0,0,0.18)'}
          onMouseLeave={e => e.currentTarget.style.boxShadow = '0 2px 12px rgba(0,0,0,0.12)'}
        >
          {/* Mini colour bar */}
          <span style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
            {CATS.map(c => (
              <span key={c.label} style={{
                width: 8, height: 8, borderRadius: '50%', background: c.color,
              }} />
            ))}
          </span>
          AQI Scale
        </button>
      )}

      {/* Expanded popup */}
      {open && (
        <div style={{
          background: 'rgba(255,255,255,0.96)',
          backdropFilter: 'blur(20px)',
          border: '1px solid var(--border)',
          borderRadius: 14,
          boxShadow: '0 8px 32px rgba(0,0,0,0.16)',
          padding: '14px 16px 10px',
          minWidth: 236,
          animation: 'legendPop 0.18s ease',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
            <div className="section-label" style={{ margin: 0 }}>Air Quality Index</div>
            <button onClick={() => setOpen(false)} aria-label="Close AQI legend" style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--muted)', fontSize: 16, lineHeight: 1, padding: 2,
            }}>✕</button>
          </div>

          {CATS.map(c => (
            <div key={c.label} style={{ marginBottom: 9 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: c.color, flexShrink: 0,
                }} />
                <span style={{ flex: 1, fontSize: 12.5, fontWeight: 600, color: 'var(--text)' }}>
                  {c.label}
                </span>
                <span style={{
                  fontSize: 11, color: 'var(--muted)',
                  fontVariantNumeric: 'tabular-nums',
                }}>
                  {c.min}–{c.max > 400 ? '500+' : c.max}
                </span>
              </div>
              <div style={{
                marginLeft: 18, marginTop: 2,
                fontSize: 10.5, color: 'var(--muted)', lineHeight: 1.35,
              }}>
                {HEALTH_TIPS[c.label]}
              </div>
            </div>
          ))}

          <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--muted)' }}>
            CPCB National Air Quality Index guidelines
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Main LeftPanel
// ─────────────────────────────────────────────────────────
export default function LeftPanel({
  loading = false,
  layers,
  onLayerChange,
  // Live data (from App.jsx after refresh)
  cityAqi,
  cleanest,
  worst,
  wardExposure,
  stations,
  // Selection
  selectedStation,
  onSelectStation,
  // Forecast chart (passed to estimate card only if shown here)
  forecast,
  forecastLoading,
  forecastOffset = 0,
  // Click-to-estimate card
  clickEstimate,
  onCloseEstimate,
}) {
  return (
    <aside className="panel" aria-label="Station controls">
      {/* 1 Search */}
      <SearchBox stations={stations} onSelect={onSelectStation} />

      {/* 2 City AQI card */}
      <CityAQICard aqi={cityAqi} loading={loading} />

      {/* 3 Ward cards */}
      <WardCards cleanest={cleanest} worst={worst} loading={loading} />

      {/* 3b Population exposure bar */}
      <PopulationExposure wardExposure={wardExposure} loading={loading} />

      <div className="panel__divider" />

      {/* 4 Layer toggles */}
      <LayerToggles layers={layers} onChange={onLayerChange} />

      <div className="panel__divider" />

      {/* 5 Station list */}
      <StationList
        stations={stations}
        selectedId={selectedStation?.id}
        onSelect={s => { onSelectStation(s); onCloseEstimate?.(); }}
        loading={loading}
      />

      {/* 6 Click-to-estimate card (only when no station selected) */}
      {!selectedStation && clickEstimate && (
        <>
          <div className="panel__divider" />
          <EstimateCard estimate={clickEstimate} onClose={onCloseEstimate} />
        </>
      )}
    </aside>
  );
}
