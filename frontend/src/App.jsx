/**
 * App.jsx — root component
 *
 * Data strategy:
 *  - On mount: useLiveData handles checking backend and pulling real AQI data.
 *  - Refresh every 5 minutes.
 *  - Forecast: /api/forecast/{station_id}. Falls back to null (no mock chart).
 *  - Attribution: /api/attribution. Error state shown; never mock text.
 *  - All API keys live in the backend; frontend has none.
 */
import React, { useState, useCallback, useMemo , useEffect } from 'react';
import './index.css';
import './App.css';
import './components/ShwasMap.css';

import TopBar from './components/TopBar';
import LeftPanel, { Legend } from './components/LeftPanel';
import RightPanel from './components/RightPanel';
import ShwasMap from './components/ShwasMap';

import { getCategory, dominantPollutant } from './utils/aqi';
import { nearestStation, ptInFeature } from './utils/geo';
import { loadWardData } from './data/wardData';
import { useLiveData } from './hooks/useLiveData';
import { forecastCoordinate } from './utils/api';

const DEFAULT_LAYERS = {
  stations: true,
  heatmap: true,
  boundaries: true,
  population: false,
  slums: false,
  windFires: true,
  hotspots: false,
  sensors: false,
};

function cityAqi(stations) {
  const vals = stations.map(s => s.aqi).filter(v => v != null && v > 0);
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}
// Which ward contains this point? Name comes from live /api/wards data.
async function placeNameAt(lat, lon, wardExposure) {
  try {
    const { geojson } = await loadWardData();
    const feat = geojson.features.find(f => ptInFeature(lon, lat, f)); // lon first
    const code = feat?.properties.wardCode;
    return wardExposure?.wards?.find(w => w.ward_id === code)?.ward_name ?? null;
  } catch {
    return null;
  }
}
// Align exposure with the ward AQI shown on the map: wards holding live
// stations use the measured value, the rest keep the backend estimate.
function reconcileExposure(wardExposure, wardAqi) {
  if (!wardExposure?.wards?.length || !wardAqi) return wardExposure;
  const byCategory = {};
  let total = 0;
  const wards = wardExposure.wards.map(w => {
    const aqi = wardAqi[w.ward_id]?.aqi ?? w.aqi;
    const pop = w.population ?? 0;
    const category = getCategory(aqi).label;
    byCategory[category] = (byCategory[category] ?? 0) + pop;
    total += pop;
    return { ...w, aqi, category };
  });
  return { ...wardExposure, wards, population_by_category: byCategory, total_population: total };
}

// Average AQI weighted by ward population (same basis as the exposure bar)
function populationWeightedAqi(wardExposure) {
  let num = 0, den = 0;
  for (const w of wardExposure?.wards ?? []) {
    if (w.aqi != null && w.population > 0) { num += w.aqi * w.population; den += w.population; }
  }
  return den > 0 ? Math.round(num / den) : null;
}
export default function App() {
  const {
    stations,
    wardAqi,
    wardExposure,
    hotspots,
    sensorSites,
    allForecasts,
    lastUpdated,
    backendDown,
    loading,
    retry,
    attribution,
    attributionLoading,
    attributionError,
    fetchAttributionFor,
    fetchForecastFor,
    forecastLoadingId,
  } = useLiveData();

  // ── Layer toggles
  const [layers, setLayers] = useState(DEFAULT_LAYERS);

  // ── Station selection
  const [selectedStation, setSelectedStation] = useState(null);

  // ── Click-to-estimate
  const [clickEstimate, setClickEstimate] = useState(null);
  const [hintVisible, setHintVisible] = useState(true);

  // ── Time slider
    // The time slider was removed: the map always shows live readings.
  const forecastOffset = 0;

  // 24-hour forecast for a clicked map point (a point has no station)
  const [pointForecast, setPointForecast] = useState(null);
  const [pointForecastLoading, setPointForecastLoading] = useState(false);
  useEffect(() => {
    if (!clickEstimate) { setPointForecast(null); setPointForecastLoading(false); return undefined; }
    let alive = true;
    setPointForecast(null);
    setPointForecastLoading(true);
    const { lat, lon } = clickEstimate;
    forecastCoordinate(lat, lon, 24, true)
      .catch(() => forecastCoordinate(lat, lon, 24, false)) // plain forecast if the range fails
      .then(d => { if (alive) setPointForecast(d?.forecast ?? null); })
      .catch(() => { if (alive) setPointForecast(null); })
      .finally(() => { if (alive) setPointForecastLoading(false); });
    return () => { alive = false; };
  }, [clickEstimate]);

  // Attribution request context for a station / a clicked point.
  // A clicked point has no pollutant readings, so it borrows the dominant
  // pollutant of the nearest station that does.
  const stationCtx = useCallback(st => ({
    lat: st.lat, lon: st.lon, aqi: st.aqi, name: st.name,
    dominantPollutant: dominantPollutant(st) ?? undefined,
  }), []);

  const pointCtx = useCallback(est => {
    const near = nearestStation(est.lat, est.lon, stations, st => dominantPollutant(st) != null);
    return {
      lat: est.lat, lon: est.lon,
      aqi: Math.round(est.estimated_aqi ?? 0),
      name: est.place ? `${est.place}, Mumbai` : 'this location',
      dominantPollutant: near ? dominantPollutant(near) : undefined,
    };
  }, [stations]);

  const handleSelectStation = useCallback(async (station) => {
    setSelectedStation(station);
    setClickEstimate(null);
    // Lazy-load forecast if it wasn't captured in the initial pre-fetch
    if (station?.id) fetchForecastFor(station.id);
    await fetchAttributionFor(stationCtx(station));
  }, [fetchAttributionFor, fetchForecastFor, stationCtx]);

  const handleClickEstimate = useCallback(async (result) => {
    const place = await placeNameAt(result.lat, result.lon, wardExposure);
    const withPlace = { ...result, place };
    setClickEstimate(withPlace);
    setSelectedStation(null);
    setHintVisible(false);
    fetchAttributionFor(pointCtx(withPlace));
  }, [fetchAttributionFor, pointCtx, wardExposure]);

  const handleCloseEstimate = useCallback(() => {
    setClickEstimate(null);
  }, []);

  const handleRetryAttribution = useCallback(() => {
    if (selectedStation) {
      fetchAttributionFor(stationCtx(selectedStation));
    } else if (clickEstimate) {
      fetchAttributionFor(pointCtx(clickEstimate));
    }
  }, [selectedStation, clickEstimate, fetchAttributionFor, stationCtx, pointCtx]);

  const handleLayerChange = useCallback((key, val) =>
    setLayers(prev => ({ ...prev, [key]: val })), []);

  // ── Derived ───────────────────────────────────────────────────────
  const liveStations = stations.filter(s => s.aqi != null && s.aqi > 0);
  const exposure = useMemo(() => reconcileExposure(wardExposure, wardAqi), [wardExposure, wardAqi]);
  const cAqi = populationWeightedAqi(exposure) ?? cityAqi(liveStations);
  const cleanest = liveStations.length ? [...liveStations].sort((a, b) => a.aqi - b.aqi)[0] : null;
  const worst = liveStations.length ? [...liveStations].sort((a, b) => b.aqi - a.aqi)[0] : null;

  const selectedContext = selectedStation
    ? { name: selectedStation.name, lat: selectedStation.lat, lon: selectedStation.lon, aqi: selectedStation.aqi }
    : clickEstimate
      ? { name: null, lat: clickEstimate.lat, lon: clickEstimate.lon, aqi: Math.round(clickEstimate.estimated_aqi ?? 0) }
      : null;

  // When backend is down, hide heatmap (it would only show interpolated mock values)
  const effectiveLayers = backendDown
    ? { ...layers, heatmap: false }
    : layers;

  const stationForecast = selectedStation ? (allForecasts || {})[selectedStation.id] : null;
  const forecast = selectedStation ? stationForecast : pointForecast;
  const forecastLoading = selectedStation
    ? forecastLoadingId === selectedStation.id && !stationForecast
    : pointForecastLoading;
  return (
    <div className="app">
      <TopBar lastUpdated={lastUpdated} />

      {/* Backend-unreachable banner */}
      {backendDown && (
        <div className="backend-banner" role="alert" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px' }}>
          <span>⚠ Backend unreachable. No live readings.</span>
          <button onClick={retry} style={{ padding: '2px 8px', borderRadius: '4px', border: '1px solid currentColor', background: 'transparent', color: 'inherit', cursor: 'pointer' }}>Retry</button>
        </div>
      )}

      <div className="app__body">
        {/* Left panel */}
        <LeftPanel
          loading={loading}
          layers={effectiveLayers}
          onLayerChange={handleLayerChange}
          cityAqi={cAqi}
          cleanest={cleanest}
          worst={worst}
          wardExposure={exposure}
          stations={liveStations}
          selectedStation={selectedStation}
          onSelectStation={handleSelectStation}
          forecast={forecast}
          forecastLoading={forecastLoading}
          clickEstimate={clickEstimate}
          onCloseEstimate={handleCloseEstimate}
          forecastOffset={forecastOffset}
        />

        {/* Map + overlays */}
        <main className="app__map" aria-label="Mumbai AQI map">
          <ShwasMap
            wardAqi={wardAqi}
            layers={effectiveLayers}
            stationPoints={stations}
            selectedStation={selectedStation}
            onStationClick={props => {
              const full = stations.find(s => s.id === props.id) ?? props;
              handleSelectStation(full);
            }}
            onClickEstimate={handleClickEstimate}
            forecastOffset={forecastOffset}
            allForecasts={allForecasts}
            windData={attribution?.wind}
            firesData={attribution?.fires}
            hotspots={hotspots}
            sensorSites={sensorSites}
          />

          <Legend />

          {layers.population && (
            <div className="pop-legend">
              <div className="pop-legend-title">Population</div>
              <div className="pop-legend-bar" />
              <div className="pop-legend-labels"><span>Low</span><span>High</span></div>
            </div>
          )}

        

          <div className={`map-hint${hintVisible ? '' : ' hidden'}`} aria-hidden="true">
            Click anywhere on the map to estimate its air quality
          </div>
        </main>

        {/* Right panel — attribution + station detail */}
        <RightPanel
          selectedStation={selectedStation}
          selectedContext={selectedContext}
          attribution={attribution}
          loading={attributionLoading}
          error={attributionError}
          onRetry={handleRetryAttribution}
          forecast={forecast}
          forecastLoading={forecastLoading}
          forecastOffset={forecastOffset}
        />
      </div>
    </div>
  );
}