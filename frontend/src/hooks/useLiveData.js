import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchLiveStations, forecastStation, getAttributionFor, checkHealth,
  fetchWardExposure, fetchHotspots, fetchSensorSites,
} from '../utils/api';
import { STATIONS as MOCK_STATIONS, createMockForecast } from '../data/mockData';
import { loadWardData } from '../data/wardData';
import { computeWardAqi, mergeWardAqi } from '../utils/geo';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';
const REFRESH_MS = 5 * 60 * 1000;

export function useLiveData() {
  const [stations, setStations] = useState([]);
  const [wardAqi, setWardAqi] = useState({});
  const [wardExposure, setWardExposure] = useState(null);   // /api/wards summary
  const [hotspots, setHotspots] = useState([]);              // /api/analytics/hotspots
  const [sensorSites, setSensorSites] = useState([]);        // /api/recommendations/sensor-placement
  const [allForecasts, setAllForecasts] = useState({});
  const [lastUpdated, setLastUpdated] = useState(null);
  const [backendDown, setBackendDown] = useState(false);
  const [loading, setLoading] = useState(true);

  // For attribution
  const [attribution, setAttribution] = useState(null);
  const [attributionLoading, setAttributionLoading] = useState(false);
  const [attributionError, setAttributionError] = useState(false);
  const [forecastLoadingId, setForecastLoadingId] = useState(null);
  const fetchLiveData = useCallback(async (isInitial = false) => {
    if (USE_MOCK) {
      if (isInitial) {
        setStations(MOCK_STATIONS);
        setBackendDown(false);
        setLastUpdated(new Date().toISOString()); // Mock gets current time
        setLoading(false);

        const results = {};
        MOCK_STATIONS.forEach(s => { results[s.id] = createMockForecast(s.aqi); });
        setAllForecasts(results);

        loadWardData().then(({ geojson }) => {
          setWardAqi(computeWardAqi(geojson, MOCK_STATIONS));
        }).catch(err => console.error(err));
      }
      return;
    }

    try {
      // First verify backend is up and get the response timestamp
      const { timestamp } = await checkHealth();

      const live = await fetchLiveStations();
      const valid = live.filter(s => s.aqi != null);

      if (valid.length > 0) {
        setStations(valid);

        // Prefer the authoritative ward exposure from the backend
        try {
          const wardData = await fetchWardExposure();
          setWardExposure(wardData);
          // Build a wardId → { aqi, count, estimated } map for ShwasMap tooltips.
          // Wards containing live stations use the measured mean; others use
          // the backend GNN/IDW estimate.
          const { geojson } = await loadWardData();
          setWardAqi(mergeWardAqi(wardData.wards, computeWardAqi(geojson, valid)));
        } catch (_) {
          // Fallback to client-side centroid calculation if backend unreachable
          try {
            const { geojson } = await loadWardData();
            setWardAqi(computeWardAqi(geojson, valid));
          } catch (err) {
            console.error('Failed to compute ward AQI:', err);
          }
        }

        // Try to find a station with an actual updated_at, otherwise use the server response date
        let updatedTime = timestamp;
        for (const s of valid) {
          if (s.updated_at) {
            updatedTime = s.updated_at;
            break;
          }
        }
        setLastUpdated(updatedTime);
      }

      setBackendDown(false);

      // Pre-fetch forecasts, hotspots, sensor sites (initial only)
      if (isInitial) {
        const fResults = {};
        const [, hotspotsRes, sensorsRes] = await Promise.allSettled([
          Promise.allSettled(
            valid.map(async s => {
              try {
                const data = await forecastStation(s.id, 24, false);
                fResults[s.id] = data.forecast ?? data.forecasts ?? (Array.isArray(data) ? data : null);
              } catch { /* Ignore */ }
            })
          ),
          fetchHotspots(100, 1.0),
          fetchSensorSites(5),
        ]);
        setAllForecasts(prev => ({ ...fResults, ...prev }));
        if (hotspotsRes.status === 'fulfilled') setHotspots(hotspotsRes.value ?? []);
        if (sensorsRes.status === 'fulfilled') setSensorSites(sensorsRes.value ?? []);
      }
    } catch (e) {
      setBackendDown(true);
      // Keep last good real data, but set lastUpdated to null to trigger "No live data"
      setLastUpdated(null);
    } finally {
      if (isInitial) setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchLiveData(true);
    const interval = setInterval(() => fetchLiveData(false), REFRESH_MS);
    return () => clearInterval(interval);
  }, [fetchLiveData]);

  const retry = useCallback(() => {
    setLoading(true);
    fetchLiveData(false).finally(() => setLoading(false));
  }, [fetchLiveData]);

  const fetchAttributionFor = useCallback(async (ctx) => {
    if (!ctx) return;
    setAttribution(null);
    setAttributionError(false);
    setAttributionLoading(true);

    try {
      const data = await getAttributionFor(ctx);
      setAttribution({ ...data, fetched_at: new Date().toISOString() });
    } catch {
      setAttributionError(true);
    } finally {
      setAttributionLoading(false);
    }
  }, []);

  // Lazy-load forecast for a station when it's selected and not yet cached
  const fetchForecastFor = useCallback(async (stationId) => {
    if (!stationId) return;
    setForecastLoadingId(stationId);
    try {
      let data;
      try {
        data = await forecastStation(stationId, 24, true);   // with confidence band
      } catch {
          data = await forecastStation(stationId, 24, false);  // plain forecast if the band fails
      }
      const fc = data.forecast ?? data.forecasts ?? (Array.isArray(data) ? data : null);
      if (fc) setAllForecasts(prev => ({ ...prev, [stationId]: fc }));
    } catch {
    // station has no forecast, so the chart stays hidden
    } finally {
      setForecastLoadingId(prev => (prev === stationId ? null : prev));
    }
  }, []);

  return {
    stations,
    wardAqi,
    wardExposure,
    hotspots,
    sensorSites,
    allForecasts,
    lastUpdated,
    backendDown,
    loading,
    forecastLoadingId,
    retry,
    attribution,
    attributionLoading,
    attributionError,
    fetchAttributionFor,
    fetchForecastFor,
  };
}