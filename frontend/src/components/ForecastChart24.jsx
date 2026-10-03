/**
 * ForecastChart24.jsx
 *
 * Always-visible 24-hour AQI forecast for the right panel.
 *  - background bands and the line colour follow the real AQI categories
 *  - a shaded range appears when the backend sends a confidence band
 *  - hover (or touch) any hour to read it
 *  - every summary number (now / peak / best time / trend) is computed
 *    from the forecast data, nothing is hardcoded
 *
 * Props:
 *   forecast  [{ timestamp, aqi, aqi_lower?, aqi_upper? }] | null
 *   loading   boolean
 *   nowAqi    current AQI of the selected place (the chart starts here)
 */
import React, { useId, useState } from 'react';
import { CATS, getCategory } from '../utils/aqi';
import './ForecastChart24.css';

// Drawing area
const W = 320, H = 156;
const PAD = { l: 28, r: 8, t: 8, b: 20 };
const PW = W - PAD.l - PAD.r;
const PH = H - PAD.t - PAD.b;
const BOTTOM = PAD.t + PH;

// Below this many usable hours we say "not enough history" instead of drawing
const MIN_VALID_HOURS = 12;

const hourLabel = ts => {
  try {
    return new Date(ts)
      .toLocaleTimeString('en-IN', { hour: 'numeric', hour12: true, timeZone: 'Asia/Kolkata' })
      .toUpperCase();
  } catch { return ''; }
};

// Smooth curve through points (Catmull-Rom converted to cubic Béziers)
function smooth(pts) {
  if (pts.length < 2) return '';
  const clampY = v => Math.min(BOTTOM, Math.max(PAD.t, v));
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = clampY(p1[1] + (p2[1] - p0[1]) / 6);
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = clampY(p2[1] - (p3[1] - p1[1]) / 6);
    d += `C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

function Shell({ children }) {
  return (
    <section className="fc24" aria-label="24-hour air quality forecast">
      <div className="fc24__head">
        <h3 className="fc24__title">Next 24 hours</h3>
      </div>
      {children}
    </section>
  );
}

export default function ForecastChart24({ forecast, loading, nowAqi }) {
  const uid = useId().replace(/:/g, '');
  const [hover, setHover] = useState(null);

  if (loading) {
    return (
      <Shell>
        <span className="skeleton" style={{ display: 'block', height: 150, borderRadius: 8 }} />
      </Shell>
    );
  }

  if (!forecast?.length) {
    return (
      <Shell>
        <p className="fc24__empty">
          A forecast is not available for this place right now. Try a nearby station.
        </p>
      </Shell>
    );
  }

  // ── Build the points: "now" first, then the forecast hours ─────────
  const hasNow = nowAqi != null && nowAqi > 0;
  const pts = [
    ...(hasNow ? [{ ts: null, aqi: nowAqi, lo: null, hi: null, isNow: true }] : []),
    ...forecast.map(f => ({ ts: f.timestamp, aqi: f.aqi, lo: f.aqi_lower ?? null, hi: f.aqi_upper ?? null, isNow: false })),
  ].map((p, i) => ({ ...p, i }));

  // A forecast value of 0 means "no data" (the backend fills gaps with 0)
  const valid = pts.filter(p => p.aqi != null && p.aqi > 0);
  const futureValid = valid.filter(p => !p.isNow);

  if (futureValid.length < MIN_VALID_HOURS) {
    return (
      <Shell>
        <p className="fc24__empty">
          This place doesn&apos;t have enough history for a full 24-hour forecast yet.
          {futureValid.length > 0 && ` Only ${futureValid.length} of 24 hours could be estimated.`}
        </p>
      </Shell>
    );
  }

  // ── Scales ──────────────────────────────────────────────────────────
  const total = pts.length - 1;
  const top = Math.max(...valid.map(p => p.hi ?? p.aqi));
  const yMax = Math.min(500, Math.max(100, Math.ceil((top * 1.15) / 50) * 50));
  const x = i => PAD.l + (i / total) * PW;
  const y = v => PAD.t + PH - (Math.min(Math.max(v, 0), yMax) / yMax) * PH;

  // ── Summary numbers (all from the data) ─────────────────────────────
  const peak = futureValid.reduce((a, b) => (b.aqi > a.aqi ? b : a));
  const best = futureValid.reduce((a, b) => (b.aqi < a.aqi ? b : a));
  const k = Math.min(8, Math.floor(futureValid.length / 2));
  const mean = arr => arr.reduce((s, p) => s + p.aqi, 0) / arr.length;
  const first = mean(futureValid.slice(0, k));
  const last = mean(futureValid.slice(-k));
  const change = first > 0 ? (last - first) / first : 0;
  const trend =
    change <= -0.08 ? { text: 'Air should get cleaner over the next 24 hours.', cls: 'better' }
      : change >= 0.08 ? { text: 'Air may get worse over the next 24 hours.', cls: 'worse' }
        : { text: 'Air quality should stay about the same.', cls: 'same' };

  const tile = (label, p, showTime) => {
    const c = getCategory(p.aqi);
    return (
      <div className="fc24__tile" style={{ borderLeftColor: c.color }}>
        <span className="fc24__tile-label">{label}</span>
        <span className="fc24__tile-val">{Math.round(p.aqi)}</span>
        <span className="fc24__tile-sub">{showTime ? (p.isNow ? 'Now' : hourLabel(p.ts)) : c.label}</span>
      </div>
    );
  };

  // ── Paths ───────────────────────────────────────────────────────────
  const linePts = valid.map(p => [x(p.i), y(p.aqi)]);
  const upperPts = valid.map(p => [x(p.i), y(p.hi ?? p.aqi)]);
  const lowerPts = valid.map(p => [x(p.i), y(p.lo ?? p.aqi)]).reverse();
  const hasBand = valid.some(p => p.hi != null && p.lo != null && p.hi > p.lo);
  const linePath = smooth(linePts);
  const areaPath = `${linePath}L${x(valid[valid.length - 1].i).toFixed(1)},${BOTTOM}L${x(valid[0].i).toFixed(1)},${BOTTOM}Z`;
  const bandPath = hasBand ? `${smooth(upperPts)}${smooth(lowerPts).replace(/^M/, 'L')}Z` : '';

  // Gradient: the line changes colour as it crosses AQI categories
  const stops = [];
  CATS.forEach((c, idx) => {
    const lo = idx === 0 ? 0 : CATS[idx - 1].max;
    stops.push({ off: Math.min(lo / yMax, 1), color: c.color });
    stops.push({ off: Math.min(c.max / yMax, 1), color: c.color });
  });

  // Y-axis guide lines at the category boundaries that fit on screen
  const guides = [0, 50, 100, 200, 300, 400, 500].filter(v => v <= yMax);
  const xTicks = [0, 6, 12, 18, 24].filter(i => i <= total);

  // ── Hover ───────────────────────────────────────────────────────────
  const onMove = e => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const svgX = ((clientX - rect.left) / rect.width) * W;
    const idx = Math.round(((svgX - PAD.l) / PW) * total);
    let nearest = valid[0];
    for (const p of valid) {
      if (Math.abs(p.i - idx) < Math.abs(nearest.i - idx)) nearest = p;
    }
    setHover(nearest);
  };

  const hc = hover ? getCategory(hover.aqi) : null;
  const tipLeft = hover ? Math.min(82, Math.max(18, (x(hover.i) / W) * 100)) : 0;

  return (
    <Shell>
      <div className="fc24__tiles">
        {hasNow && tile('Now', valid[0], false)}
        {tile('Peak', peak, true)}
        {tile('Best time', best, true)}
      </div>

      <div className="fc24__plot">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="fc24__svg"
          role="img"
          aria-label={`Forecast for the next 24 hours. Peak AQI ${Math.round(peak.aqi)} at ${hourLabel(peak.ts)}. Lowest AQI ${Math.round(best.aqi)} at ${hourLabel(best.ts)}.`}
          onMouseMove={onMove}
          onTouchMove={onMove}
          onTouchStart={onMove}
          onMouseLeave={() => setHover(null)}
          onTouchEnd={() => setHover(null)}
        >
          <defs>
            <linearGradient id={`g${uid}`} gradientUnits="userSpaceOnUse" x1="0" y1={BOTTOM} x2="0" y2={PAD.t}>
              {stops.map((s, n) => <stop key={n} offset={s.off} stopColor={s.color} />)}
            </linearGradient>
          </defs>

          {/* Category bands */}
          {CATS.map((c, idx) => {
            const lo = idx === 0 ? 0 : CATS[idx - 1].max;
            if (lo >= yMax) return null;
            const hi = Math.min(c.max, yMax);
            const h = y(lo) - y(hi);
            return (
              <g key={c.label}>
                <rect x={PAD.l} y={y(hi)} width={PW} height={h} fill={c.color} opacity="0.11" />
                {h >= 16 && (
                  <text x={W - PAD.r - 3} y={y(hi) + 10} textAnchor="end" fontSize="8" fontWeight="600"
                    fill={c.color} opacity="0.9">{c.label}</text>
                )}
              </g>
            );
          })}

          {/* Guide lines + y labels */}
          {guides.map(v => (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke="#17241E" strokeOpacity="0.08" strokeDasharray="2 3" />
              <text x={PAD.l - 5} y={y(v) + 3} textAnchor="end" fontSize="8" fill="var(--muted)">{v}</text>
            </g>
          ))}

          {/* Time labels */}
          {xTicks.map(i => (
            <text key={i} x={x(i)} y={H - 5} fontSize="8.5" fill="var(--muted)"
              textAnchor={i === 0 ? 'start' : i === total ? 'end' : 'middle'}>
              {i === 0 && hasNow ? 'Now' : hourLabel(pts[i]?.ts)}
            </text>
          ))}

          {/* Confidence range */}
          {hasBand && <path d={bandPath} fill="var(--forest)" opacity="0.13" />}

          {/* Area + line */}
          <path d={areaPath} fill={`url(#g${uid})`} opacity="0.2" />
          <path d={linePath} fill="none" stroke={`url(#g${uid})`} strokeWidth="2.6"
            strokeLinecap="round" strokeLinejoin="round" />

          {/* Dots every 3 hours, bigger dot for "now" */}
          {valid.filter(p => !p.isNow && p.i % 3 === 0).map(p => (
            <circle key={p.i} cx={x(p.i)} cy={y(p.aqi)} r="2.4" fill={getCategory(p.aqi).color}
              stroke="#fff" strokeWidth="1" />
          ))}
          {hasNow && (
            <circle cx={x(valid[0].i)} cy={y(valid[0].aqi)} r="4.2" fill={getCategory(valid[0].aqi).color}
              stroke="#fff" strokeWidth="2" />
          )}

          {/* Hover marker */}
          {hover && (
            <g pointerEvents="none">
              <line x1={x(hover.i)} x2={x(hover.i)} y1={PAD.t} y2={BOTTOM} stroke="#17241E" strokeOpacity="0.3" strokeDasharray="3 2" />
              <circle cx={x(hover.i)} cy={y(hover.aqi)} r="4.6" fill={hc.color} stroke="#fff" strokeWidth="2" />
            </g>
          )}
        </svg>

        {hover && (
          <div className="fc24__tip" style={{ left: `${tipLeft}%` }} role="status">
            <strong>{hover.isNow ? 'Now' : hourLabel(hover.ts)}</strong>
            <span><i className="fc24__dot" style={{ background: hc.color }} />AQI {Math.round(hover.aqi)}, {hc.label}</span>
            {hover.lo != null && hover.hi != null && hover.hi > hover.lo && (
              <span className="fc24__tip-range">likely {Math.round(hover.lo)} to {Math.round(hover.hi)}</span>
            )}
          </div>
        )}
      </div>

      <p className={`fc24__trend fc24__trend--${trend.cls}`}>
        {trend.text}
        {hasBand && <span className="fc24__note"> The shaded area is the likely range.</span>}
      </p>
    </Shell>
  );
}