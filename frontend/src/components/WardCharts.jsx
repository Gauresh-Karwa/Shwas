/**
 * WardCharts.jsx
 *
 * Three visual panels added to the Ward Action Centre detail view:
 *   1. ForecastChart   - recharts AreaChart: current AQI + 12-h model forecast
 *   2. WardMiniMap     - pure-SVG bubble map of all 24 wards ranked by exposure
 *   3. ExposureBar     - horizontal bar: selected ward vs city median AQI
 */
import React, { useMemo } from 'react';
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
    ReferenceLine, ResponsiveContainer, Label,
    PieChart, Pie, Cell, RadialBarChart, RadialBar, Legend,
} from 'recharts';
import {
    MapContainer, TileLayer, CircleMarker, Popup,
    Tooltip as LTooltip, useMap,
} from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { getCategory } from '../utils/aqi';
import { actionCards, advisoryCards, SIGNALS } from '../utils/actions';

/* AQI band thresholds – must stay in sync with backend CATEGORY_BANDS */
const AQI_BANDS = [
    { lo: 0, hi: 50, label: 'Good', color: '#22c55e' },
    { lo: 51, hi: 100, label: 'Satisfactory', color: '#84cc16' },
    { lo: 101, hi: 200, label: 'Moderate', color: '#f59e0b' },
    { lo: 201, hi: 300, label: 'Poor', color: '#f97316' },
    { lo: 301, hi: 400, label: 'Very Poor', color: '#ef4444' },
    { lo: 401, hi: 500, label: 'Severe', color: '#7c3aed' },
];

function bandFor(aqi) {
    return AQI_BANDS.find(b => aqi <= b.hi) ?? AQI_BANDS[AQI_BANDS.length - 1];
}

/* ------------------------------------------------------------------ */
/*  1. Forecast Chart                                                   */
/* ------------------------------------------------------------------ */

const CustomDot = ({ cx, cy, payload }) => {
    if (!payload?.forecast) return null;
    const band = bandFor(payload.aqi);
    return <circle cx={cx} cy={cy} r={4} fill={band.color} stroke="#fff" strokeWidth={1.5} />;
};

const CustomTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0].payload;
    const band = bandFor(d.aqi);
    return (
        <div style={{
            background: '#fff', border: `1px solid ${band.color}`,
            borderRadius: 8, padding: '8px 12px', fontSize: 12,
            boxShadow: '0 4px 12px rgba(0,0,0,.1)',
        }}>
            <div style={{ fontWeight: 700, color: band.color, marginBottom: 2 }}>
                AQI {Math.round(d.aqi)} — {band.label}
            </div>
            <div style={{ color: '#6b7280' }}>
                {d.label}
                {d.forecast && <span style={{ marginLeft: 6, color: '#9ca3af', fontSize: 11 }}>(forecast)</span>}
            </div>
        </div>
    );
};

/**
 * ForecastChart
 *
 * Props:
 *   ward        - full ward object from /api/actions
 *   currentAqi  - number, current AQI
 */
export function ForecastChart({ ward, currentAqi }) {
    // Collect forecast points from the first live card that has them
    const forecastPoints = useMemo(() => {
        const cards = [...actionCards(ward), ...advisoryCards(ward)];
        for (const c of cards) {
            const fc = c.forecast_without_action;
            if (fc?.hours_ahead && fc?.predicted_aqi) return [fc];
        }
        return [];
    }, [ward]);

    const points = useMemo(() => {
        const now = { hour: 0, aqi: currentAqi, label: 'Now', forecast: false };
        const fcs = forecastPoints.map(fc => ({
            hour: fc.hours_ahead,
            aqi: fc.predicted_aqi,
            label: `+${fc.hours_ahead}h forecast`,
            forecast: true,
        }));
        // Fill in evenly-spaced intermediate ticks between now and the first forecast
        const steps = [];
        if (fcs.length > 0) {
            const target = fcs[0];
            const intervals = Math.min(target.hour, 6);
            for (let i = 1; i < intervals; i++) {
                const t = i / intervals;
                steps.push({
                    hour: Math.round(target.hour * (i / intervals)),
                    aqi: currentAqi + (target.aqi - currentAqi) * t,
                    label: `+${Math.round(target.hour * (i / intervals))}h (interpolated)`,
                    forecast: true,
                });
            }
        }
        return [now, ...steps, ...fcs].sort((a, b) => a.hour - b.hour);
    }, [currentAqi, forecastPoints]);

    if (points.length < 2) return null;

    const minAqi = Math.max(0, Math.min(...points.map(p => p.aqi)) - 20);
    const maxAqi = Math.min(500, Math.max(...points.map(p => p.aqi)) + 30);
    const currentBand = bandFor(currentAqi);
    const forecastBand = forecastPoints.length ? bandFor(forecastPoints[0].aqi) : currentBand;
    const rising = forecastPoints.length && forecastPoints[0].aqi > currentAqi + 5;
    const falling = forecastPoints.length && forecastPoints[0].aqi < currentAqi - 5;

    return (
        <div className="wc-panel">
            <div className="wc-panel__hd">
                <span className="section-label">AQI Forecast Trajectory</span>
                <span className="wc-trend" style={{ color: rising ? '#ef4444' : falling ? '#22c55e' : '#6b7280' }}>
                    {rising ? 'Worsening' : falling ? 'Improving' : 'Steady'}
                    {forecastPoints.length > 0 && ` → ${Math.round(forecastPoints[0].aqi)} (${forecastBand.label}) in ${forecastPoints[0].hours_ahead}h`}
                </span>
            </div>

            <ResponsiveContainer width="100%" height={160}>
                <AreaChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <defs>
                        <linearGradient id={`fcGrad-${ward.ward_id}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor={forecastBand.color} stopOpacity={0.25} />
                            <stop offset="95%" stopColor={forecastBand.color} stopOpacity={0.02} />
                        </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis
                        dataKey="hour"
                        tickFormatter={h => h === 0 ? 'Now' : `+${h}h`}
                        tick={{ fontSize: 10, fill: '#9ca3af' }}
                        axisLine={false} tickLine={false}
                    />
                    <YAxis
                        domain={[minAqi, maxAqi]}
                        tick={{ fontSize: 10, fill: '#9ca3af' }}
                        axisLine={false} tickLine={false} width={36}
                    />
                    {/* Draw AQI band reference lines */}
                    {AQI_BANDS.filter(b => b.hi > minAqi && b.lo < maxAqi && b.lo > 0).map(b => (
                        <ReferenceLine key={b.lo} y={b.lo} stroke={b.color}
                            strokeDasharray="4 4" strokeOpacity={0.4} strokeWidth={1}>
                            <Label value={b.label} position="insideTopLeft"
                                style={{ fontSize: 9, fill: b.color, opacity: 0.7 }} />
                        </ReferenceLine>
                    ))}
                    <ReferenceLine y={currentAqi} stroke={currentBand.color}
                        strokeWidth={1.5} strokeDasharray="6 3">
                        <Label value="Current" position="right"
                            style={{ fontSize: 9, fill: currentBand.color }} />
                    </ReferenceLine>
                    <Tooltip content={<CustomTooltip />} />
                    <Area
                        type="monotone" dataKey="aqi"
                        stroke={forecastBand.color} strokeWidth={2}
                        fill={`url(#fcGrad-${ward.ward_id})`}
                        dot={<CustomDot />}
                        activeDot={{ r: 5, fill: forecastBand.color, stroke: '#fff', strokeWidth: 2 }}
                    />
                </AreaChart>
            </ResponsiveContainer>
            <p className="wc-note">Model forecast without intervention. Not a guaranteed outcome.</p>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/*  2. Ward Priority Mini-Map (pure SVG, no tiles)                     */
/* ------------------------------------------------------------------ */

/*
 * Ward centroids — approximate lat/lon centres for Mumbai's 24 wards.
 * Used to position the bubbles on the SVG canvas.
 */
const WARD_CENTROIDS = {
    'A': [18.916, 72.830], 'B': [18.945, 72.843], 'C': [18.944, 72.830],
    'D': [18.967, 72.806], 'E': [18.975, 72.848], 'F/S': [19.002, 72.857],
    'F/N': [19.043, 72.862], 'G/S': [19.001, 72.815], 'G/N': [19.040, 72.837],
    'H/E': [19.063, 72.865], 'H/W': [19.058, 72.826], 'K/E': [19.115, 72.868],
    'K/W': [19.113, 72.833], 'L': [19.073, 72.887], 'M/E': [19.053, 72.925],
    'M/W': [19.054, 72.898], 'N': [19.096, 72.909], 'P/S': [19.162, 72.849],
    'P/N': [19.186, 72.840], 'R/S': [19.206, 72.852], 'R/C': [19.226, 72.862],
    'R/N': [19.249, 72.856], 'S': [19.143, 72.923], 'T': [19.175, 72.946],
};

/* ------------------------------------------------------------------ */
/*  2. Ward Detail Map — Leaflet tile map, zoomed to selected ward     */
/* ------------------------------------------------------------------ */

/*
 * Neighbour lookup: wards sharing a boundary or within ~3 km.
 * Approximated from the Mumbai ward adjacency map.
 */
const WARD_NEIGHBOURS = {
    'A': ['B', 'C', 'D'],
    'B': ['A', 'C', 'E'],
    'C': ['A', 'B', 'D', 'E', 'F/S'],
    'D': ['A', 'C', 'G/S'],
    'E': ['B', 'C', 'F/S', 'F/N'],
    'F/S': ['C', 'E', 'F/N', 'G/N', 'G/S'],
    'F/N': ['E', 'F/S', 'G/N', 'L'],
    'G/S': ['D', 'F/S', 'G/N', 'H/W'],
    'G/N': ['F/S', 'F/N', 'G/S', 'H/E', 'H/W', 'L'],
    'H/E': ['G/N', 'H/W', 'K/E', 'L'],
    'H/W': ['G/S', 'G/N', 'H/E', 'K/W'],
    'K/E': ['H/E', 'K/W', 'L', 'P/S'],
    'K/W': ['H/W', 'K/E', 'P/S', 'P/N'],
    'L': ['F/N', 'G/N', 'H/E', 'K/E', 'M/E', 'M/W', 'N'],
    'M/E': ['L', 'M/W', 'N', 'S'],
    'M/W': ['L', 'M/E', 'N'],
    'N': ['L', 'M/E', 'M/W', 'S'],
    'P/S': ['K/E', 'K/W', 'P/N', 'R/S'],
    'P/N': ['K/W', 'P/S', 'R/S', 'R/C'],
    'R/S': ['P/S', 'P/N', 'R/C'],
    'R/C': ['P/N', 'R/S', 'R/N'],
    'R/N': ['R/C'],
    'S': ['M/E', 'N', 'T'],
    'T': ['S'],
};


/** Smoothly re-centres the map when the selected ward changes. */
function RecenterOnWard({ lat, lon, zoom }) {
    const map = useMap();
    React.useEffect(() => {
        map.setView([lat, lon], zoom, { animate: true, duration: 0.5 });
    }, [lat, lon, zoom, map]);
    return null;
}

/* Zone descriptions from the action engine WARD_ZONES lookup */
const WARD_ZONES_FE = {
    'A': 'Island City — South Mumbai',
    'B': 'Island City — Port Corridor',
    'C': 'Island City — High Density Core',
    'D': 'Island City — Coastal Ridge',
    'E': 'Island City — Central Harbor',
    'F/S': 'Island City — Industrial Heritage',
    'F/N': 'Island City — Northern Transit Hub',
    'G/S': 'Island City — Commercial Redevelopment',
    'G/N': 'Island City — Northern Gateway',
    'H/E': 'Western Suburbs — Airport & Rail Corridor',
    'H/W': 'Western Suburbs — Coastal Residential',
    'K/E': 'Western Suburbs — Commercial & Industrial Axis',
    'K/W': 'Western Suburbs — High-Density Coastal Hub',
    'P/S': 'Western Suburbs — Suburban Transit Core',
    'P/N': 'Western Suburbs — Suburban Valley Basin',
    'R/S': 'Western Suburbs — Northern Industrial-Residential',
    'R/C': 'Western Suburbs — Borivali Central Axis',
    'R/N': 'Western Suburbs — Northern Frontier',
    'L': 'Eastern Suburbs — Central Logistics Hub',
    'M/E': 'Eastern Suburbs — SWM Basin & Creek Corridor',
    'M/W': 'Eastern Suburbs — Harbor & Petrochemical Basin',
    'N': 'Eastern Suburbs — Industrial-Commercial Corridor',
    'S': 'Eastern Suburbs — Industrial Belt & Hill Buffer',
    'T': 'Eastern Suburbs — Northern Foothill Frontier',
};

const SIGNAL_LABELS = {
    waste_burning: 'Waste Burning',
    traffic: 'Traffic Peak',
    stagnation: 'Stagnation',
    dust: 'Dust',
    forecast_crossing: 'Forecast Rise',
    inflow: 'Smoke Inflow',
};

const SIGNAL_ICONS = {
    waste_burning: '',
    traffic: '',
    stagnation: '',
    dust: '',
    forecast_crossing: '',
    inflow: '',
};

export function WardMiniMap({ wards, selectedWardId, onSelect }) {
    const wardMap = useMemo(() => {
        const m = {};
        for (const w of wards ?? []) m[w.ward_id] = w;
        return m;
    }, [wards]);

    const selectedWard = wardMap[selectedWardId];
    const centroid = selectedWardId ? WARD_CENTROIDS[selectedWardId] : null;
    const [selLat, selLon] = centroid ?? [19.076, 72.877];

    const selectedAqi = selectedWard?.current_aqi ?? 0;
    const selBand = bandFor(selectedAqi);
    const zone = WARD_ZONES_FE[selectedWardId] ?? '';

    /* Active live cards for the selected ward */
    const liveCards = useMemo(() =>
        selectedWard ? actionCards(selectedWard) : [],
        [selectedWard]);

    /* Group live cards by signal for the signals strip */
    const signalGroups = useMemo(() => {
        const g = {};
        for (const c of liveCards) {
            if (!g[c.signal]) g[c.signal] = { signal: c.signal, severity: c.severity, count: 0 };
            else if (c.severity === 'high') g[c.signal].severity = 'high';
            g[c.signal].count++;
        }
        return Object.values(g);
    }, [liveCards]);

    /* Neighbour wards */
    const neighbours = useMemo(() => {
        if (!selectedWardId) return [];
        return (WARD_NEIGHBOURS[selectedWardId] ?? []).map(nid => {
            const nc = WARD_CENTROIDS[nid];
            const nw = wardMap[nid];
            if (!nc) return null;
            const aqi = nw?.current_aqi ?? 0;
            return { id: nid, lat: nc[0], lon: nc[1], aqi, band: bandFor(aqi), name: nw?.ward_name ?? nid };
        }).filter(Boolean);
    }, [selectedWardId, wardMap]);

    /* Rank of selected ward (1 = worst) */
    const wardRank = useMemo(() => {
        const sorted = Object.entries(wardMap)
            .map(([id, w]) => ({ id, aqi: w?.current_aqi ?? 0 }))
            .sort((a, b) => b.aqi - a.aqi);
        const idx = sorted.findIndex(w => w.id === selectedWardId);
        return idx >= 0 ? idx + 1 : null;
    }, [wardMap, selectedWardId]);

    /* City ranking strip: all 24 wards sorted high → low */
    const cityRanked = useMemo(() =>
        Object.entries(WARD_CENTROIDS)
            .map(([id]) => {
                const w = wardMap[id];
                return { id, aqi: w?.current_aqi ?? 0, name: w?.ward_name ?? id };
            })
            .sort((a, b) => b.aqi - a.aqi),
        [wardMap]);

    return (
        <div className="wc-panel wc-map-card">

            {/* ── Header ── */}
            <div className="wc-panel__hd" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
                    <span className="section-label">
                        {selectedWard ? selectedWard.ward_name : 'Ward Detail Map'}
                        {selectedWardId && <span className="wc-ward-id-badge">Ward {selectedWardId}</span>}
                    </span>
                    {selectedAqi > 0 && (
                        <span className="wc-insight-tag"
                            style={{ color: selBand.color, borderColor: selBand.color }}>
                            AQI {Math.round(selectedAqi)} &middot; {selBand.label}
                        </span>
                    )}
                </div>
                {zone && <span className="wc-zone-label">{zone}</span>}
            </div>

            {/* ── Leaflet map ── */}
            {centroid ? (
                <div className="wc-leaflet-wrap">
                    <MapContainer
                        center={[selLat, selLon]}
                        zoom={14}
                        zoomControl={false}
                        attributionControl={true}
                        scrollWheelZoom={false}
                        style={{ width: '100%', height: '100%', borderRadius: 8 }}
                    >
                        {/* OpenStreetMap — completely free, no API key */}
                        <TileLayer
                            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                            maxZoom={19}
                        />
                        <RecenterOnWard lat={selLat} lon={selLon} zoom={14} />

                        {/* Neighbour wards — subtle context circles */}
                        {neighbours.map(n => (
                            <CircleMarker key={n.id} center={[n.lat, n.lon]} radius={20}
                                pathOptions={{
                                    fillColor: n.band.color, fillOpacity: 0.22,
                                    color: n.band.color, weight: 2,
                                }}
                                eventHandlers={{ click: () => onSelect?.(n.id) }}>
                                <LTooltip permanent direction="center"
                                    className="wc-map-nb-label">{n.id}</LTooltip>
                                <Popup>
                                    <strong>{n.name} (Ward {n.id})</strong><br />
                                    AQI {Math.round(n.aqi)} &middot; {n.band.label}<br />
                                    <em style={{ fontSize: 11 }}>Click to select this ward</em>
                                </Popup>
                            </CircleMarker>
                        ))}

                        {/* Selected ward — outer dashed boundary ring */}
                        <CircleMarker center={[selLat, selLon]} radius={44}
                            pathOptions={{
                                fillColor: selBand.color, fillOpacity: 0.08,
                                color: selBand.color, weight: 2.5, dashArray: '8 5',
                            }} />

                        {/* Selected ward — inner solid AQI circle */}
                        <CircleMarker center={[selLat, selLon]} radius={18}
                            pathOptions={{
                                fillColor: selBand.color, fillOpacity: 0.9,
                                color: '#fff', weight: 3,
                            }}>
                            <LTooltip permanent direction="center"
                                className="wc-map-sel-label">
                                {Math.round(selectedAqi)}
                            </LTooltip>
                            <Popup>
                                <strong>{selectedWard?.ward_name} (Ward {selectedWardId})</strong><br />
                                AQI {Math.round(selectedAqi)} &middot; {selBand.label}<br />
                                {zone}<br />
                                {(selectedWard?.population ?? 0).toLocaleString('en-IN')} residents
                            </Popup>
                        </CircleMarker>

                        {/* CAAQMS station blue pin */}
                        {selectedWard?.station_lat && selectedWard?.station_lon && (
                            <CircleMarker
                                center={[selectedWard.station_lat, selectedWard.station_lon]}
                                radius={8}
                                pathOptions={{
                                    fillColor: '#1D4ED8', fillOpacity: 0.95,
                                    color: '#fff', weight: 2.5,
                                }}>
                                <Popup>
                                    <strong>CAAQMS Station</strong><br />
                                    {selectedWard.nearest_station}<br />
                                    {selectedWard.distance_to_station_km != null &&
                                        `${selectedWard.distance_to_station_km.toFixed(1)} km from ward centre`}
                                </Popup>
                            </CircleMarker>
                        )}

                        {/* Active fire markers */}
                        {liveCards
                            .filter(c => c.signal === 'waste_burning' && c.fire_lat && c.fire_lon)
                            .map((c, i) => (
                                <CircleMarker key={i}
                                    center={[c.fire_lat, c.fire_lon]} radius={9}
                                    pathOptions={{
                                        fillColor: '#ef4444', fillOpacity: 0.92,
                                        color: '#fff', weight: 2,
                                    }}>
                                    <Popup>
                                        <strong>Active fire detection</strong><br />
                                        {c.action_title}<br />
                                        Confidence: {c.confidence}
                                    </Popup>
                                </CircleMarker>
                            ))
                        }
                    </MapContainer>
                </div>
            ) : (
                <div className="wc-map-empty">Select a ward to see its detail map</div>
            )}

            {/* ── 4-column stat strip ── */}
            {selectedWard && (
                <div className="wc-map-strip wc-map-strip--4">
                    <div className="wc-map-strip__item">
                        <span className="wc-map-strip__lbl">Population</span>
                        <span className="wc-map-strip__val">
                            {(selectedWard.population ?? 0).toLocaleString('en-IN')}
                        </span>
                    </div>
                    <div className="wc-map-strip__item">
                        <span className="wc-map-strip__lbl">City Rank</span>
                        <span className="wc-map-strip__val" style={{ color: wardRank <= 6 ? '#dc2626' : 'inherit' }}>
                            {wardRank != null ? `#${wardRank}` : '—'} <span style={{ fontSize: 9, fontWeight: 400 }}>/ 24</span>
                        </span>
                    </div>
                    <div className="wc-map-strip__item">
                        <span className="wc-map-strip__lbl">Live Alerts</span>
                        <span className="wc-map-strip__val" style={{ color: liveCards.length ? '#dc2626' : 'inherit' }}>
                            {liveCards.length}
                        </span>
                    </div>
                    <div className="wc-map-strip__item">
                        <span className="wc-map-strip__lbl">Station</span>
                        <span className="wc-map-strip__val wc-map-strip__val--trunc">
                            {selectedWard.distance_to_station_km != null
                                ? `${selectedWard.distance_to_station_km.toFixed(1)} km`
                                : '—'}
                        </span>
                    </div>
                </div>
            )}

            {/* ── Active signals strip ── */}
            {signalGroups.length > 0 && (
                <div className="wc-signal-strip">
                    <div className="wc-signal-strip__label">Active signals</div>
                    <div className="wc-signal-strip__chips">
                        {signalGroups.map(g => (
                            <span key={g.signal}
                                className={`wc-signal-chip wc-signal-chip--${g.severity}`}>
                                {SIGNAL_ICONS[g.signal] || ''} {SIGNAL_LABELS[g.signal] || g.signal}
                                {g.count > 1 && <span className="wc-signal-chip__count">{g.count}</span>}
                            </span>
                        ))}
                    </div>
                </div>
            )}

            {/* ── Nearest station detail ── */}
            {selectedWard?.nearest_station && (
                <div className="wc-station-row">
                    <span className="wc-station-dot" />
                    <span className="wc-station-name">{selectedWard.nearest_station}</span>
                    <span className="wc-station-dist">
                        {selectedWard.distance_to_station_km != null
                            ? `${selectedWard.distance_to_station_km.toFixed(1)} km`
                            : ''}
                    </span>
                </div>
            )}

            {/* ── City ranking dot strip ── */}
            <div className="wc-city-strip">
                <div className="wc-city-strip__label">All 24 wards &rarr; click to switch</div>
                <div className="wc-city-strip__dots">
                    {cityRanked.map(({ id, aqi, name }) => {
                        const b = bandFor(aqi);
                        const isSel = id === selectedWardId;
                        return (
                            <button key={id} type="button"
                                className={`wc-city-dot${isSel ? ' wc-city-dot--sel' : ''}`}
                                style={{ background: b.color, outlineColor: isSel ? b.color : 'transparent' }}
                                title={`${name} (${id}) — AQI ${Math.round(aqi)} · ${b.label}`}
                                onClick={() => onSelect?.(id)}
                                aria-current={isSel ? 'true' : undefined}>
                                <span className="wc-city-dot__id">{id}</span>
                            </button>
                        );
                    })}
                </div>
            </div>

            <p className="wc-note">
                Dashed ring = ward area. Blue circle = CAAQMS station. Red circle = fire detection.
                Coloured rings = neighbours &mdash; click to switch.
            </p>
        </div>
    );
}

/* ------------------------------------------------------------------ */

/*  3. Exposure comparison bar                                          */
/* ------------------------------------------------------------------ */

export function ExposureBar({ ward, allWards }) {
    const cityMedian = useMemo(() => {
        const vals = (allWards ?? [])
            .map(w => w.current_aqi)
            .filter(v => v != null)
            .sort((a, b) => a - b);
        if (!vals.length) return null;
        return vals[Math.floor(vals.length / 2)];
    }, [allWards]);

    const cityMax = useMemo(() =>
        Math.max(...(allWards ?? []).map(w => w.current_aqi ?? 0), 1),
        [allWards]);

    if (!ward || cityMedian == null) return null;

    const aqi = ward.current_aqi ?? 0;
    const wardBand = bandFor(aqi);
    const medBand = bandFor(cityMedian);
    const wardPct = Math.min(100, (aqi / cityMax) * 100);
    const medPct = Math.min(100, (cityMedian / cityMax) * 100);
    const diff = aqi - cityMedian;

    return (
        <div className="wc-panel">
            <div className="wc-panel__hd">
                <span className="section-label">Exposure vs. City Median</span>
                <span className="wc-trend" style={{
                    color: diff > 20 ? '#ef4444' : diff < -20 ? '#22c55e' : '#6b7280'
                }}>
                    {diff > 0 ? `+${Math.round(diff)} above` : diff < 0 ? `${Math.round(diff)} below` : 'At'} city median
                </span>
            </div>

            <div className="wc-exp">
                <div className="wc-exp__row">
                    <span className="wc-exp__label">{ward.ward_name}</span>
                    <div className="wc-exp__track">
                        <div className="wc-exp__fill"
                            style={{ width: `${wardPct}%`, background: wardBand.color }} />
                    </div>
                    <span className="wc-exp__val" style={{ color: wardBand.color }}>
                        {Math.round(aqi)}
                    </span>
                </div>
                <div className="wc-exp__row">
                    <span className="wc-exp__label">City median</span>
                    <div className="wc-exp__track">
                        <div className="wc-exp__fill"
                            style={{ width: `${medPct}%`, background: medBand.color }} />
                    </div>
                    <span className="wc-exp__val" style={{ color: medBand.color }}>
                        {Math.round(cityMedian)}
                    </span>
                </div>
            </div>

            {/* Population-weighted exposure note */}
            <div className="wc-exp__pop">
                <span className="wc-pop-dot" style={{ background: wardBand.color }} />
                {ward.ward_name}: {(ward.population ?? 0).toLocaleString('en-IN')} residents
                exposed to {wardBand.label} air ({Math.round(aqi)} AQI)
            </div>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/*  4. Ward Insights Panel                                              */
/*                                                                      */
/*  Sub-sections:                                                       */
/*    A. Health Impact Ring  — estimated % population above WHO AQI    */
/*    B. Source Attribution  — donut from signal confidence scores     */
/*    C. Above-Baseline Band — current vs. city best/worst             */
/* ------------------------------------------------------------------ */

/*
 * WHO Air Quality Guideline 2021: PM2.5 annual mean 5 µg/m³.
 * For a 24-h mean at AQI > 100 (Moderate, ~35 µg/m³) we flag the ward
 * as having elevated acute exposure risk. AQI > 200 = high risk (WHO IT-1
 * 24-h mean of 75 µg/m³). AQI > 300 = severe.
 *
 * Source: WHO Global Air Quality Guidelines 2021,
 *         https://www.who.int/publications/i/item/9789240034228
 */
function riskLevel(aqi) {
    if (aqi >= 300) return { label: 'Severe', pct: 95, color: '#7c3aed', who: 'AQI > 300: greatly exceeds WHO IT-1 24-h guideline (75 µg/m³ PM2.5)' };
    if (aqi >= 200) return { label: 'High', pct: 75, color: '#ef4444', who: 'AQI > 200: exceeds WHO IT-1 24-h guideline (75 µg/m³ PM2.5)' };
    if (aqi >= 150) return { label: 'Elevated', pct: 55, color: '#f97316', who: 'AQI > 150: approaches WHO IT-1 24-h guideline' };
    if (aqi >= 100) return { label: 'Moderate', pct: 35, color: '#f59e0b', who: 'AQI > 100: exceeds WHO 24-h PM2.5 guideline of 15 µg/m³' };
    if (aqi >= 50) return { label: 'Low', pct: 12, color: '#84cc16', who: 'AQI 50–100: above WHO annual mean guideline (5 µg/m³)' };
    return { label: 'Good', pct: 3, color: '#22c55e', who: 'AQI < 50: near WHO annual mean guideline' };
}

function HealthImpactRing({ ward }) {
    const aqi = ward.current_aqi ?? 0;
    const pop = ward.population ?? 0;
    const risk = riskLevel(aqi);
    const atRisk = Math.round(pop * risk.pct / 100);
    const data = [
        { name: 'At risk', value: risk.pct, fill: risk.color },
        { name: 'Baseline', value: 100 - risk.pct, fill: '#e5e7eb' },
    ];

    return (
        <div className="wc-insight-block">
            <div className="wc-insight-block__hd">
                <span className="wc-insight-label">Health Impact Estimate</span>
                <span className="wc-insight-tag" style={{ color: risk.color, borderColor: risk.color }}>
                    {risk.label} risk
                </span>
            </div>
            <div className="wc-health">
                <div style={{ width: 110, height: 110, flexShrink: 0 }}>
                    <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                            <Pie data={data} cx="50%" cy="50%" innerRadius={32} outerRadius={50}
                                startAngle={90} endAngle={-270} dataKey="value" strokeWidth={0}>
                                {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
                            </Pie>
                        </PieChart>
                    </ResponsiveContainer>
                </div>
                <div className="wc-health__text">
                    <div className="wc-health__num" style={{ color: risk.color }}>
                        ~{atRisk.toLocaleString('en-IN')}
                    </div>
                    <div className="wc-health__desc">
                        residents ({risk.pct}%) at elevated acute exposure risk
                    </div>
                    <div className="wc-health__who">{risk.who}</div>
                </div>
            </div>
        </div>
    );
}

/*
 * Source attribution: estimate percentage contribution from each
 * emission source type using the confidence scores of fired signals.
 *
 * Methodology: each active signal's confidence score is normalised
 * across all fired signals. Unknown remainder is labelled "Regional/Other".
 * This is a first-order estimation only, not a receptor modelling result.
 */
const SOURCE_COLORS = {
    waste_burning: '#7c3aed',
    traffic: '#f97316',
    dust: '#d97706',
    stagnation: '#6366f1',
    forecast_crossing: '#14b8a6',
    inflow: '#0ea5e9',
    other: '#d1d5db',
};

const SOURCE_LABELS = {
    waste_burning: 'Open burning',
    traffic: 'Vehicular exhaust',
    dust: 'Construction / road dust',
    stagnation: 'Stagnant air amplification',
    forecast_crossing: 'Rising pollution front',
    inflow: 'Upwind regional smoke',
    other: 'Regional / unknown',
};

const CustomPieTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0];
    return (
        <div style={{
            background: '#fff', border: `1px solid ${d.payload.fill}`,
            borderRadius: 8, padding: '6px 10px', fontSize: 11.5,
            boxShadow: '0 4px 12px rgba(0,0,0,.1)',
        }}>
            <div style={{ fontWeight: 700, color: d.payload.fill }}>{d.name}</div>
            <div style={{ color: '#6b7280' }}>{d.value}% estimated contribution</div>
        </div>
    );
};

function SourceAttribution({ ward }) {
    const live = useMemo(() => actionCards(ward), [ward]);
    const adv = useMemo(() => advisoryCards(ward).filter(c => !c.baseline), [ward]);
    const allCards = [...live, ...adv];

    const data = useMemo(() => {
        const fired = allCards.filter(c => c.confidence_score > 0);
        if (!fired.length) return [{ name: 'Regional / unknown', value: 100, fill: SOURCE_COLORS.other }];
        const total = fired.reduce((s, c) => s + c.confidence_score, 0);
        const slices = fired.map(c => ({
            name: SOURCE_LABELS[c.signal] ?? c.signal,
            value: Math.round((c.confidence_score / total) * 85),  // leave 15% for "other"
            fill: SOURCE_COLORS[c.signal] ?? SOURCE_COLORS.other,
        }));
        const assigned = slices.reduce((s, d) => s + d.value, 0);
        slices.push({ name: 'Regional / unknown', value: 100 - assigned, fill: SOURCE_COLORS.other });
        return slices;
    }, [allCards]);

    if (!allCards.length) return null;

    return (
        <div className="wc-insight-block">
            <div className="wc-insight-block__hd">
                <span className="wc-insight-label">Estimated Source Attribution</span>
            </div>
            <div className="wc-attr">
                <div style={{ width: 120, height: 120, flexShrink: 0 }}>
                    <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                            <Pie data={data} cx="50%" cy="50%" innerRadius={30} outerRadius={55}
                                dataKey="value" strokeWidth={1} stroke="#fff">
                                {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
                            </Pie>
                            <Tooltip content={<CustomPieTooltip />} />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
                <div className="wc-attr__legend">
                    {data.map((d, i) => (
                        <div key={i} className="wc-attr__row">
                            <span className="wc-attr__dot" style={{ background: d.fill }} />
                            <span className="wc-attr__name">{d.name}</span>
                            <span className="wc-attr__pct" style={{ color: d.fill }}>{d.value}%</span>
                        </div>
                    ))}
                </div>
            </div>
            <p className="wc-note" style={{ marginTop: 4 }}>
                First-order estimate from signal confidence scores. Not a receptor modelling result.
            </p>
        </div>
    );
}

/*
 * Above-baseline: compare this ward's current AQI to the city's best
 * and worst ward today. Shows where it sits on the city spectrum.
 */
function AboveBaseline({ ward, allWards }) {
    const aqi = ward.current_aqi ?? 0;

    const { best, worst, cityPct } = useMemo(() => {
        const vals = (allWards ?? []).map(w => w.current_aqi ?? 0).filter(v => v > 0);
        if (!vals.length) return { best: aqi, worst: aqi, cityPct: 50 };
        const mn = Math.min(...vals);
        const mx = Math.max(...vals);
        const pct = mx === mn ? 50 : Math.round(((aqi - mn) / (mx - mn)) * 100);
        return { best: Math.round(mn), worst: Math.round(mx), cityPct: pct };
    }, [aqi, allWards]);

    const band = bandFor(aqi);

    // Seasonal context: Oct-Nov in Mumbai is post-monsoon shoulder season.
    // Typical Oct median AQI for Mumbai: ~90-120 (Satisfactory to Moderate).
    const SEASONAL_MEDIAN = 105;
    const vsSeasonalPct = Math.round(((aqi - SEASONAL_MEDIAN) / SEASONAL_MEDIAN) * 100);
    const vsSeasonalText = vsSeasonalPct > 0
        ? `${vsSeasonalPct}% above Oct–Nov seasonal average`
        : vsSeasonalPct < 0
            ? `${Math.abs(vsSeasonalPct)}% below Oct–Nov seasonal average`
            : 'At the Oct–Nov seasonal average';

    return (
        <div className="wc-insight-block">
            <div className="wc-insight-block__hd">
                <span className="wc-insight-label">City Ranking and Seasonal Context</span>
            </div>

            {/* Spectrum bar: best ward → this ward → worst ward */}
            <div className="wc-spectrum">
                <div className="wc-spectrum__labels">
                    <span>Best: {best}</span>
                    <span style={{ color: band.color, fontWeight: 700 }}>
                        {ward.ward_name}: {Math.round(aqi)}
                    </span>
                    <span>Worst: {worst}</span>
                </div>
                <div className="wc-spectrum__track">
                    {/* AQI band gradient */}
                    <div className="wc-spectrum__gradient" />
                    {/* Marker for this ward */}
                    <div className="wc-spectrum__marker" style={{ left: `${cityPct}%`, background: band.color }} />
                </div>
                <div className="wc-spectrum__rank">
                    This ward is in the <strong style={{ color: band.color }}>
                        {cityPct >= 75 ? 'top 25% worst' : cityPct >= 50 ? 'upper half' : cityPct >= 25 ? 'lower half' : 'top 25% best'}
                    </strong> of all monitored wards today
                </div>
            </div>

            {/* Seasonal comparison */}
            <div className="wc-season">
                <span className="wc-season__dot" style={{ background: vsSeasonalPct > 20 ? '#ef4444' : vsSeasonalPct > 0 ? '#f59e0b' : '#22c55e' }} />
                <span className="wc-season__text">{vsSeasonalText}</span>
                <span className="wc-season__src">(Oct–Nov Mumbai baseline: AQI ~105)</span>
            </div>
        </div>
    );
}

/**
 * WardInsights — the full insights panel.
 * Mount this below the action cards in WardDetail.
 */
export function WardInsights({ ward, allWards }) {
    if (!ward) return null;
    const hasLive = actionCards(ward).length > 0 || advisoryCards(ward).filter(c => !c.baseline).length > 0;

    return (
        <div className="wc-panel wc-insights">
            <div className="wc-panel__hd">
                <span className="section-label">Ward Insights</span>
                <span className="wc-trend" style={{ color: '#6b7280' }}>Based on live signal data</span>
            </div>

            <HealthImpactRing ward={ward} />

            {hasLive && <SourceAttribution ward={ward} />}

            <AboveBaseline ward={ward} allWards={allWards} />
        </div>
    );
}

/* ------------------------------------------------------------------ */
/*  5. City-Wide Alert Feed                                             */
/*                                                                      */
/*  A consolidated, priority-sorted view of every active signal        */
/*  fired across all 24 wards. Replaces the ward detail pane when      */
/*  the user switches to "City View".                                  */
/* ------------------------------------------------------------------ */

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };
const SIGNAL_ICON = {
    waste_burning: '⬛',   // solid square = fire/smoke
    traffic: '▶',
    dust: '◈',
    stagnation: '◎',
    forecast_crossing: '▲',
    inflow: '→',
};

function FeedItem({ item, isSelected, onSelect }) {
    const band = bandFor(item.aqi);
    const sevColors = { high: '#1a3d2e', medium: '#5a8a6a', low: '#a8c5b4' };
    const borderColor = sevColors[item.severity] ?? '#d1d5db';

    return (
        <button
            type="button"
            className={`caf-item${isSelected ? ' caf-item--selected' : ''}`}
            style={{ borderLeftColor: borderColor }}
            onClick={() => onSelect(item.wardId)}
            aria-current={isSelected ? 'true' : undefined}
        >
            <div className="caf-item__top">
                <span className={`caf-sev caf-sev--${item.severity}`}>
                    {item.severity.charAt(0).toUpperCase() + item.severity.slice(1)}
                </span>
                <span className="caf-signal">
                    {SIGNAL_ICON[item.signal] ?? '•'} {SOURCE_LABELS[item.signal] ?? item.signal}
                </span>
                <span className="caf-aqi" style={{ color: band.color }}>
                    AQI {Math.round(item.aqi)}
                </span>
            </div>

            <div className="caf-item__ward">
                <strong>{item.wardName}</strong>
                <span className="caf-ward-id">Ward {item.wardId}</span>
                <span className="caf-pop">{Math.round(item.population / 1000)}k residents</span>
            </div>

            <p className="caf-item__title">{item.actionTitle}</p>

            {item.evidence[0] && (
                <p className="caf-item__evidence">{item.evidence[0]}</p>
            )}

            <div className="caf-item__foot">
                <span className="caf-conf">Confidence: {item.confidence}</span>
                {item.advisory && <span className="caf-adv-tag">Advisory</span>}
            </div>
        </button>
    );
}

function FeedSummaryBar({ items }) {
    const high = items.filter(i => i.severity === 'high').length;
    const medium = items.filter(i => i.severity === 'medium').length;
    const adv = items.filter(i => i.advisory).length;
    const wards = new Set(items.map(i => i.wardId)).size;

    return (
        <div className="caf-summary">
            <div className="caf-summary__stat">
                <span className="caf-summary__num" style={{ color: '#1a3d2e' }}>{high}</span>
                <span className="caf-summary__lbl">High</span>
            </div>
            <div className="caf-summary__stat">
                <span className="caf-summary__num" style={{ color: '#5a8a6a' }}>{medium}</span>
                <span className="caf-summary__lbl">Medium</span>
            </div>
            <div className="caf-summary__stat">
                <span className="caf-summary__num">{adv}</span>
                <span className="caf-summary__lbl">Advisory</span>
            </div>
            <div className="caf-summary__stat">
                <span className="caf-summary__num">{wards}</span>
                <span className="caf-summary__lbl">Wards affected</span>
            </div>
            <div className="caf-summary__stat">
                <span className="caf-summary__num">{items.length}</span>
                <span className="caf-summary__lbl">Total alerts</span>
            </div>
        </div>
    );
}

/**
 * CityAlertFeed
 *
 * Props:
 *   wards        – all ward objects from /api/actions
 *   generatedAt  – ISO string from data.generated_at
 *   selectedId   – currently selected ward_id
 *   onSelect     – (wardId) => void
 */
export function CityAlertFeed({ wards, generatedAt, selectedId, onSelect }) {
    const [signalFilter, setSignalFilter] = React.useState('all');

    // Flatten every non-baseline card across all wards into one feed list
    const allItems = useMemo(() => {
        const out = [];
        for (const ward of wards ?? []) {
            const cards = (ward.cards ?? []).filter(c => !c.baseline);
            for (const c of cards) {
                out.push({
                    cardId: c.card_id,
                    wardId: ward.ward_id,
                    wardName: ward.ward_name,
                    aqi: ward.current_aqi ?? 0,
                    population: ward.population ?? 0,
                    signal: c.signal,
                    severity: c.severity,
                    confidence: c.confidence,
                    advisory: c.advisory,
                    actionTitle: c.action_title,
                    evidence: c.evidence ?? [],
                    priorityScore: c.priority_score ?? 0,
                });
            }
        }
        // Sort: high severity first, then priority score descending
        out.sort((a, b) => {
            const sd = (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9);
            if (sd !== 0) return sd;
            return b.priorityScore - a.priorityScore;
        });
        return out;
    }, [wards]);

    // Available signal types for filter chips
    const signals = useMemo(() => {
        const seen = new Set(allItems.map(i => i.signal));
        return [...seen];
    }, [allItems]);

    const filtered = useMemo(() =>
        signalFilter === 'all' ? allItems : allItems.filter(i => i.signal === signalFilter),
        [allItems, signalFilter]);

    const asOf = useMemo(() => {
        if (!generatedAt) return null;
        try {
            return new Date(generatedAt).toLocaleTimeString('en-IN', {
                hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata',
            }) + ' IST';
        } catch { return null; }
    }, [generatedAt]);

    return (
        <div className="caf">
            <div className="caf__hd">
                <div>
                    <div className="section-label">City-Wide Alert Feed</div>
                    <h2 className="caf__title">All Active Alerts — Mumbai (24 Wards)</h2>
                    {asOf && <p className="caf__ts">Data as of {asOf}</p>}
                </div>
            </div>

            {allItems.length === 0 ? (
                <div className="caf__empty">
                    <div className="caf__empty-badge">All Clear</div>
                    <p className="caf__empty-text">No live alert signals detected across any ward right now. Routine operational mitigations are in effect.</p>
                </div>
            ) : (
                <>
                    <FeedSummaryBar items={allItems} />

                    {/* Signal type filter chips */}
                    <div className="caf__chips" role="group" aria-label="Filter by signal type">
                        {['all', ...signals].map(s => (
                            <button key={s} type="button"
                                className={`act-filter${signalFilter === s ? ' act-filter--on' : ''}`}
                                onClick={() => setSignalFilter(s)}>
                                {s === 'all' ? 'All signals' : (SOURCE_LABELS[s] ?? s)}
                            </button>
                        ))}
                    </div>

                    <div className="caf__list">
                        {filtered.length === 0 && (
                            <p className="station-list__empty">No alerts match this signal filter.</p>
                        )}
                        {filtered.map(item => (
                            <FeedItem
                                key={item.cardId}
                                item={item}
                                isSelected={item.wardId === selectedId}
                                onSelect={onSelect}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}

/* ================================================================== */
/*  6. Mitigation Simulator                                            */
/*                                                                      */
/*  Shows two AQI trajectories on the same chart:                      */
/*    - Red  → forecast WITHOUT intervention (from card data)          */
/*    - Green → estimated forecast WITH all recommended actions        */
/*                                                                      */
/*  Action effectiveness is derived from peer-reviewed source ranges   */
/*  cited in action_rules.yaml. This is a model estimate only.        */
/* ================================================================== */

/*
 * Science-backed effectiveness ranges per signal type.
 * Sources cited in action_rules.yaml / backend rationale:
 *  - waste_burning:     CPCB MSW Guidelines 2016; open burning PM2.5 reducible 40-70%
 *  - dust:              BMC 28-pt C&D Guidelines 2019; wet sweeping 30-60%
 *  - traffic:           MCGM ITMS SOP; signal opt + anti-idling → 10-20% corridor NO2/CO
 *  - stagnation:        Road sweeping + C&D sealing → local accumulation -15-25%
 *  - forecast_crossing: Pre-emptive water spray + advisory → peak reduction 20-35%
 *  - inflow:            Advisory only — no direct local source reduction (0%)
 */
const EFFECTIVENESS = {
    waste_burning: { lo: 0.40, hi: 0.70, label: 'Open burning suppression', unit: 'PM2.5' },
    dust: { lo: 0.30, hi: 0.60, label: 'Wet sweeping + C&D sealing', unit: 'PM10' },
    traffic: { lo: 0.10, hi: 0.20, label: 'Signal optimisation + anti-idling', unit: 'NO2/CO' },
    stagnation: { lo: 0.15, hi: 0.25, label: 'Road sweeping + C&D stop-work', unit: 'PM2.5/PM10' },
    forecast_crossing: { lo: 0.20, hi: 0.35, label: 'Pre-emptive dust control', unit: 'PM10' },
    inflow: { lo: 0.00, hi: 0.00, label: 'Advisory only (no local source reduction)', unit: '—' },
};

function simulateWithAction(cards, forecastAqi) {
    const live = (cards ?? []).filter(c => !c.advisory && !c.baseline);
    if (!live.length) return null;

    let reductionLo = 0, reductionHi = 0;
    const seen = new Set();

    for (const card of live) {
        const eff = EFFECTIVENESS[card.signal];
        if (!eff || seen.has(card.signal)) continue;
        seen.add(card.signal);

        const conf = card.confidence_score ?? 0.5;
        const weight = 0.5 + conf * 0.5;
        reductionLo += forecastAqi * eff.lo * weight;
        reductionHi += forecastAqi * eff.hi * weight;
    }

    const floor = 50;
    const capped = v => Math.max(floor, Math.round(forecastAqi - v));

    return {
        low: capped(reductionHi),
        mid: capped((reductionLo + reductionHi) / 2),
        high: capped(reductionLo),
        reductionLo: Math.round(reductionLo),
        reductionHi: Math.round(reductionHi),
    };
}

const SimTooltip = ({ active, payload }) => {
    if (!active || !payload?.length) return null;
    return (
        <div style={{
            background: '#fff', border: '1px solid #e5e7eb',
            borderRadius: 8, padding: '8px 12px', fontSize: 12,
            boxShadow: '0 4px 12px rgba(0,0,0,.12)',
        }}>
            {payload.map((p, i) => (
                <div key={i} style={{ color: p.color, fontWeight: 700, marginBottom: 2 }}>
                    {p.name}: AQI {Math.round(p.value)}
                </div>
            ))}
            {payload[0] && (
                <div style={{ color: '#9ca3af', fontSize: 10.5, marginTop: 3 }}>
                    {payload[0].payload.label}
                </div>
            )}
        </div>
    );
};

export function MitigationSimulator({ ward, isOpen, onClose }) {
    const cards = ward?.cards ?? [];
    const live = cards.filter(c => !c.advisory && !c.baseline);
    const currentAqi = ward?.current_aqi ?? 0;

    const forecastCard = useMemo(() =>
        live.reduce((best, c) => {
            const p = c.forecast_without_action?.predicted_aqi ?? 0;
            return p > (best?.forecast_without_action?.predicted_aqi ?? 0) ? c : best;
        }, null),
        [live]);

    const forecastAqi = forecastCard?.forecast_without_action?.predicted_aqi ?? currentAqi;
    const forecastHours = forecastCard?.forecast_without_action?.hours_ahead ?? 6;

    const sim = useMemo(() => simulateWithAction(cards, forecastAqi), [cards, forecastAqi]);

    const chartData = useMemo(() => {
        const steps = 7;
        return Array.from({ length: steps }, (_, i) => {
            const t = i / (steps - 1);
            const noAction = Math.round(currentAqi + (forecastAqi - currentAqi) * t);
            const withAct = sim ? Math.round(currentAqi + (sim.mid - currentAqi) * t) : noAction;
            return {
                label: i === 0 ? 'Now' : `+${Math.round(forecastHours * t)}h`,
                noAction,
                withAct,
            };
        });
    }, [currentAqi, forecastAqi, forecastHours, sim]);

    const noActBand = bandFor(forecastAqi);
    const withActBand = sim ? bandFor(sim.mid) : noActBand;
    const pop = ward?.population ?? 0;
    const riskBefore = riskLevel(forecastAqi).pct;
    const riskAfter = sim ? riskLevel(sim.mid).pct : riskBefore;
    const peopleHelped = Math.round(pop * Math.max(0, riskBefore - riskAfter) / 100);

    if (!isOpen) return null;

    return (
        <div className="sim-overlay" role="dialog" aria-modal="true" aria-label="Mitigation simulation">
            <div className="sim-panel">

                {/* ── Header ─────────────────────────────────────────── */}
                <div className="sim-hd">
                    <div>
                        <div className="section-label">Mitigation Impact Simulator</div>
                        <h2 className="sim-title">
                            {ward?.ward_name} — Ward {ward?.ward_id}
                        </h2>
                        <p className="sim-sub">
                            Estimated AQI trajectory with vs. without all {live.length} recommended
                            action{live.length !== 1 ? 's' : ''} applied simultaneously.
                        </p>
                    </div>
                    <button type="button" className="sim-close" onClick={onClose}>✕ Close</button>
                </div>

                {/* ── Summary stat bar ───────────────────────────────── */}
                <div className="sim-stats">
                    <div className="sim-stat">
                        <span className="sim-stat__num" style={{ color: bandFor(currentAqi).color }}>
                            {Math.round(currentAqi)}
                        </span>
                        <span className="sim-stat__lbl">Current AQI</span>
                    </div>
                    <div className="sim-stat sim-stat--sep">→</div>
                    <div className="sim-stat">
                        <span className="sim-stat__num" style={{ color: noActBand.color }}>
                            {Math.round(forecastAqi)}
                        </span>
                        <span className="sim-stat__lbl">+{forecastHours}h no action</span>
                    </div>
                    {sim && <>
                        <div className="sim-stat sim-stat--sep" style={{ color: '#22c55e' }}>vs.</div>
                        <div className="sim-stat">
                            <span className="sim-stat__num" style={{ color: withActBand.color }}>
                                {sim.mid}
                            </span>
                            <span className="sim-stat__lbl">+{forecastHours}h with action</span>
                        </div>
                        <div className="sim-stat">
                            <span className="sim-stat__num" style={{ color: '#22c55e' }}>
                                −{sim.reductionLo}–{sim.reductionHi}
                            </span>
                            <span className="sim-stat__lbl">AQI reduction est.</span>
                        </div>
                    </>}
                </div>

                {/* ── Comparison chart ───────────────────────────────── */}
                <div className="sim-chart-wrap">
                    <ResponsiveContainer width="100%" height={220}>
                        <AreaChart data={chartData} margin={{ top: 12, right: 24, left: 0, bottom: 0 }}>
                            <defs>
                                <linearGradient id="simGradNo" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor={noActBand.color} stopOpacity={0.2} />
                                    <stop offset="95%" stopColor={noActBand.color} stopOpacity={0.02} />
                                </linearGradient>
                                <linearGradient id="simGradWith" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="5%" stopColor="#22c55e" stopOpacity={0.18} />
                                    <stop offset="95%" stopColor="#22c55e" stopOpacity={0.02} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
                            <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#9ca3af' }}
                                axisLine={false} tickLine={false} />
                            <YAxis domain={['auto', 'auto']}
                                tick={{ fontSize: 10, fill: '#9ca3af' }}
                                axisLine={false} tickLine={false} width={36} />
                            <Tooltip content={<SimTooltip />} />
                            <Area type="monotone" dataKey="noAction" name="Without action"
                                stroke={noActBand.color} strokeWidth={2} strokeDasharray="5 3"
                                fill="url(#simGradNo)"
                                dot={{ r: 3, fill: noActBand.color, strokeWidth: 0 }} />
                            {sim && (
                                <Area type="monotone" dataKey="withAct" name="With all actions"
                                    stroke="#22c55e" strokeWidth={2.5}
                                    fill="url(#simGradWith)"
                                    dot={{ r: 4, fill: '#22c55e', stroke: '#fff', strokeWidth: 1.5 }} />
                            )}
                        </AreaChart>
                    </ResponsiveContainer>
                    <div className="sim-chart-legend">
                        <span className="sim-legend-item">
                            <span className="sim-legend-dash" style={{ borderTopColor: noActBand.color }} />
                            Without intervention
                        </span>
                        {sim && (
                            <span className="sim-legend-item">
                                <span className="sim-legend-solid" style={{ background: '#22c55e' }} />
                                With all actions applied
                            </span>
                        )}
                    </div>
                </div>

                {/* ── Per-action table ───────────────────────────────── */}
                {live.length > 0 && (
                    <div className="sim-table-wrap">
                        <div className="section-label" style={{ marginBottom: 8 }}>
                            Action-by-Action Effectiveness Breakdown
                        </div>
                        <table className="sim-table">
                            <thead>
                                <tr>
                                    <th>Priority</th>
                                    <th>Action</th>
                                    <th>Pollutant targeted</th>
                                    <th>Est. AQI reduction</th>
                                    <th>Confidence</th>
                                </tr>
                            </thead>
                            <tbody>
                                {live.map(c => {
                                    const eff = EFFECTIVENESS[c.signal];
                                    const conf = c.confidence_score ?? 0.5;
                                    const weight = 0.5 + conf * 0.5;
                                    const rLo = eff ? Math.round(forecastAqi * eff.lo * weight) : 0;
                                    const rHi = eff ? Math.round(forecastAqi * eff.hi * weight) : 0;
                                    return (
                                        <tr key={c.card_id}>
                                            <td>
                                                <span className={`caf-sev caf-sev--${c.severity}`}>
                                                    {c.severity.charAt(0).toUpperCase() + c.severity.slice(1)}
                                                </span>
                                            </td>
                                            <td className="sim-table__title">{c.action_title}</td>
                                            <td className="sim-table__unit">{eff?.unit ?? '—'}</td>
                                            <td>
                                                {rHi > 0
                                                    ? <span className="sim-reduction">−{rLo}–{rHi} pts</span>
                                                    : <span style={{ color: '#9ca3af' }}>Advisory only</span>}
                                            </td>
                                            <td><span className="sim-conf">{c.confidence}</span></td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}

                {/* ── Population benefit ─────────────────────────────── */}
                {sim && peopleHelped > 0 && (
                    <div className="sim-benefit">
                        <span className="sim-benefit__num" style={{ color: '#22c55e' }}>
                            ~{peopleHelped.toLocaleString('en-IN')}
                        </span>
                        <span className="sim-benefit__text">
                            residents could move from{' '}
                            <strong style={{ color: noActBand.color }}>{noActBand.label}</strong> to{' '}
                            <strong style={{ color: withActBand.color }}>{withActBand.label}</strong>{' '}
                            conditions if all {live.length} action{live.length !== 1 ? 's' : ''} are
                            executed within their time windows.
                        </span>
                    </div>
                )}

                {/* ── Disclaimer ─────────────────────────────────────── */}
                <p className="sim-disclaimer">
                    Model estimate only. Effectiveness ranges sourced from BMC 28-pt C&D Guidelines
                    (2019), CPCB Dust Control Guidelines (2022), MCGM ITMS SOP, and SAFAR-India AQI
                    modelling. Actual reduction depends on field execution speed, wind conditions, and
                    background pollution. Not a guaranteed forecast.
                </p>
            </div>
        </div>
    );
}
