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
import React, { useState, useCallback } from 'react';
import './index.css';
import './App.css';
import './components/ShwasMap.css';

import TopBar     from './components/TopBar';
import LeftPanel, { Legend } from './components/LeftPanel';
import RightPanel from './components/RightPanel';
import ShwasMap   from './components/ShwasMap';
import TimeSlider from './components/TimeSlider';

import { getCategory } from './utils/aqi';
import { useLiveData } from './hooks/useLiveData';

import { SEED_STATIONS } from './data/stations';

const DEFAULT_LAYERS = {
  stations:   true,
  heatmap:    true,
  boundaries: true,
  population: false,
  slums:      false,
  windFires:  true,
};

function cityAqi(stations) {
  const vals = stations.map(s => s.aqi).filter(v => v != null && v > 0);
  if (!vals.length) return null;
  return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
}

export default function App() {
  const {
    stations,
    wardAqi, // For future use
    allForecasts,
    lastUpdated,
    backendDown,
    loading,
    retry,
    attribution,
    attributionLoading,
    attributionError,
    fetchAttributionFor
  } = useLiveData(SEED_STATIONS);

  // ── Layer toggles
  const [layers, setLayers] = useState(DEFAULT_LAYERS);

  // ── Station selection
  const [selectedStation,    setSelectedStation]    = useState(null);
  
  // ── Click-to-estimate
  const [clickEstimate,  setClickEstimate]  = useState(null);
  const [hintVisible,    setHintVisible]    = useState(true);

  // ── Time slider
  const [forecastOffset, setForecastOffset] = useState(0);

  const handleSelectStation = useCallback(async (station) => {
    setSelectedStation(station);
    setClickEstimate(null);
    await fetchAttributionFor(station);
  }, [fetchAttributionFor]);

  const handleClickEstimate = useCallback((result) => {
    setClickEstimate(result);
    setSelectedStation(null);
    setHintVisible(false);
    fetchAttributionFor({
      lat:  result.lat,
      lon:  result.lon,
      aqi:  Math.round(result.estimated_aqi ?? 0),
      name: 'Selected location',
    });
  }, [fetchAttributionFor]);

  const handleCloseEstimate = useCallback(() => {
    setClickEstimate(null);
  }, []);

  const handleRetryAttribution = useCallback(() => {
    const ctx = selectedStation || clickEstimate;
    if (ctx) {
      fetchAttributionFor(ctx);
    }
  }, [selectedStation, clickEstimate, fetchAttributionFor]);

  const handleLayerChange = useCallback((key, val) =>
    setLayers(prev => ({ ...prev, [key]: val })), []);

  // ── Derived ───────────────────────────────────────────────────────
  const liveStations = stations.filter(s => s.aqi != null && s.aqi > 0);
  const cAqi     = cityAqi(liveStations) ?? null;
  const cleanest = liveStations.length ? [...liveStations].sort((a, b) => a.aqi - b.aqi)[0]   : null;
  const worst    = liveStations.length ? [...liveStations].sort((a, b) => b.aqi - a.aqi)[0]   : null;

  const selectedContext = selectedStation
    ? { name: selectedStation.name, lat: selectedStation.lat, lon: selectedStation.lon, aqi: selectedStation.aqi }
    : clickEstimate
    ? { name: null, lat: clickEstimate.lat, lon: clickEstimate.lon, aqi: Math.round(clickEstimate.estimated_aqi ?? 0) }
    : null;

  // When backend is down, hide heatmap (it would only show interpolated mock values)
  const effectiveLayers = backendDown
    ? { ...layers, heatmap: false }
    : layers;

  const forecastsReady = Object.keys(allForecasts || {}).length > 0;
  const forecast = selectedStation ? (allForecasts || {})[selectedStation.id] : null;
  const forecastLoading = false; // Simplified since it's pre-fetched

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
          />

          <Legend />

          {layers.population && (
            <div className="pop-legend">
              <div className="pop-legend-title">Population</div>
              <div className="pop-legend-bar" />
              <div className="pop-legend-labels"><span>Low</span><span>High</span></div>
            </div>
          )}

          <TimeSlider
            offset={forecastOffset}
            onChange={setForecastOffset}
            hasForecasts={forecastsReady}
          />

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
