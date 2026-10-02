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
        { label: 'Cleanest ward',      s: cleanest },
        { label: 'Most polluted ward', s: worst    },
      ].map(({ label, s }) => {
        const cat = getCategory(s?.aqi);
        return (
          <div className="ward-card" key={label}>
            <div className="ward-card__label">{label}</div>
            <div className="ward-card__row">
              <span className="ward-card__name">{s?.name ?? '—'}</span>
              <span className="aqi-badge" style={{ background: cat.color, fontSize: 11 }}>{s?.aqi ?? '—'}</span>
            </div>
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
  { key: 'stations',   label: 'Stations'       },
  { key: 'heatmap',    label: 'Heatmap'        },
  { key: 'boundaries', label: 'Boundaries'     },
  { key: 'population', label: 'Population'     },
  { key: 'slums',      label: 'Slum clusters'  },
  { key: 'windFires',  label: 'Wind and fires' },
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
// Legend (exported — rendered inside map area)
// ─────────────────────────────────────────────────────────
export function Legend() {
  return (
    <div style={{
      position: 'absolute', bottom: 24, right: 16,
      background: 'var(--white)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)',
      padding: '12px 14px', minWidth: 168, zIndex: 100,
    }}>
      <div className="section-label" style={{ marginBottom: 10 }}>Air Quality Index</div>
      {CATS.map(c => (
        <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: c.color, flexShrink: 0 }} />
          <span style={{ flex: 1, fontSize: 12.5, color: 'var(--text)' }}>{c.label}</span>
          <span style={{ fontSize: 11, color: 'var(--muted)', fontVariantNumeric: 'tabular-nums' }}>
            {c.min}–{c.max > 400 ? '500+' : c.max}
          </span>
        </div>
      ))}
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
