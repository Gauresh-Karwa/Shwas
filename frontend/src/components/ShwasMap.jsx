/**
 * ShwasMap.jsx
 *
 * MapLibre GL JS map with:
 *  1. OpenFreeMap "positron" style (keyless) → Esri raster fallback
 *  2. Land + water tint via setPaintProperty
 *  3. 24 BMC ward boundaries (BMC_Wards.geojson) with hover tooltip
 *  4. Canvas heatmap:
 *       - 20 col × 27 row grid over Mumbai bounding box
 *       - Ray-casting land mask (only cells whose centre is in a ward)
 *       - Immediate IDW skeleton from station data
 *       - Progressive API refinement (8 concurrent, in-memory cache)
 *       - Rendered as MapLibre canvas source with raster-resampling:linear
 *  5. Click-to-estimate: dashed pin + calls /api/interpolate
 *  6. 16 px station circles (radius=8 in MapLibre)
 */

import React, { useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { loadWardData } from '../data/wardData';
import { computeWardAqi } from '../utils/geo';
import { getAQIColor, getCategory, describeHotspot } from '../utils/aqi';
import { airMassBounds } from '../utils/airMass';
import { addAirMassLayers, setAirMass } from '../utils/airMassLayer';
import { interpolate as apiInterpolate } from '../utils/api';
import './ShwasMap.css';

// ── Geographic constants ──────────────────────────────────────────
const GEO = { W: 72.75, E: 73.02, S: 18.88, N: 19.30 };

// ── Heatmap grid ──────────────────────────────────────────────────
// Smooth surface: ~400x520 canvas, clipped to ward polygons, blurred
const SMOOTH_COLS = 400, SMOOTH_ROWS = 520;

// MapLibre canvas-source corner coordinates (clockwise from top-left)
const HEAT_COORDS = [
  [GEO.W, GEO.N],
  [GEO.E, GEO.N],
  [GEO.E, GEO.S],
  [GEO.W, GEO.S],
];

// ── Gaussian blur (3-pass box-blur approximation, O(pixels)) ──────
// Box widths that approximate a gaussian of the given sigma in n passes.
function boxesForGauss(sigma, n) {
  const wIdeal = Math.sqrt((12 * sigma * sigma) / n + 1);
  let wl = Math.floor(wIdeal);
  if (wl % 2 === 0) wl--;
  const wu = wl + 2;
  const mIdeal = (12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4);
  const m = Math.round(mIdeal);
  return Array.from({ length: n }, (_, i) => (i < m ? wl : wu));
}

// One edge-clamped running-sum box pass over RGBA data (horizontal or vertical).
function boxBlurPass(src, dst, width, height, r, horizontal) {
  const len = horizontal ? width : height;
  const lines = horizontal ? height : width;
  const stride = horizontal ? 4 : width * 4;
  const lineStep = horizontal ? width * 4 : 4;
  const inv = 1 / (r + r + 1);

  for (let line = 0; line < lines; line++) {
    const base = line * lineStep;
    for (let c = 0; c < 4; c++) {
      const first = src[base + c];
      const last = src[base + (len - 1) * stride + c];
      let val = (r + 1) * first;
      for (let j = 0; j < r; j++) val += src[base + j * stride + c];
      for (let j = 0; j <= r; j++) {
        val += src[base + (j + r) * stride + c] - first;
        dst[base + j * stride + c] = val * inv;
      }
      for (let j = r + 1; j < len - r; j++) {
        val += src[base + (j + r) * stride + c] - src[base + (j - r - 1) * stride + c];
        dst[base + j * stride + c] = val * inv;
      }
      for (let j = len - r; j < len; j++) {
        val += last - src[base + (j - r - 1) * stride + c];
        dst[base + j * stride + c] = val * inv;
      }
    }
  }
}

function gaussianBlur(ctx, width, height, sigma = 6) {
  const img = ctx.getImageData(0, 0, width, height);
  const a = img.data;
  const b = new Uint8ClampedArray(a.length);
  for (const size of boxesForGauss(sigma, 3)) {
    const r = (size - 1) / 2;
    boxBlurPass(a, b, width, height, r, true);
    boxBlurPass(b, a, width, height, r, false);
  }
  ctx.putImageData(img, 0, 0);
}

// ── Trace all ward polygons into the current canvas path ──────────
function traceWardPath(ctx, wardsGeoJSON, bounds) {
  const [[w, s], [e, n]] = bounds;
  const scaleX = SMOOTH_COLS / (e - w);
  const scaleY = SMOOTH_ROWS / (n - s);

  const traceRing = ring => {
    ring.forEach(([lng, lat], i) => {
      const x = (lng - w) * scaleX;
      const y = (n - lat) * scaleY; // flip Y
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
  };

  ctx.beginPath();
  wardsGeoJSON.features.forEach(feat => {
    const coords = feat.geometry.coordinates;
    if (feat.geometry.type === 'Polygon') {
      coords.forEach(traceRing);
    } else if (feat.geometry.type === 'MultiPolygon') {
      coords.forEach(poly => poly.forEach(traceRing));
    }
  });
}

// ── AQI colour → [r, g, b] (cached) ───────────────────────────────
const rgbCache = {};
function aqiRgb(aqi) {
  const hex = getAQIColor(aqi);
  if (!rgbCache[hex]) {
    rgbCache[hex] = [
      parseInt(hex.slice(1, 3), 16),
      parseInt(hex.slice(3, 5), 16),
      parseInt(hex.slice(5, 7), 16),
    ];
  }
  return rgbCache[hex];
}

// ── Styles ────────────────────────────────────────────────────────
const OFM_STYLE = 'https://tiles.openfreemap.org/styles/positron';
const ESRI_FALLBACK = {
  version: 8,
  sources: {
    esri: {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      attribution: 'Esri, HERE, Garmin',
    },
    'esri-ref': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
    },
  },
  layers: [
    { id: 'esri-base', type: 'raster', source: 'esri', minzoom: 0, maxzoom: 22 },
    { id: 'esri-labels', type: 'raster', source: 'esri-ref', minzoom: 0, maxzoom: 22 },
  ],
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
};

// ── Point-in-polygon (ray casting) ────────────────────────────────
function ptInRing(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    if (((yi > y) !== (yj > y)) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function ptInFeature(lng, lat, feat) {
  const g = feat.geometry;
  if (g.type === 'Polygon')
    return ptInRing(lng, lat, g.coordinates[0]);
  if (g.type === 'MultiPolygon')
    return g.coordinates.some(p => ptInRing(lng, lat, p[0]));
  return false;
}

function isLand(lng, lat, features) {
  return features.some(f => ptInFeature(lng, lat, f));
}

// ── IDW fallback ──────────────────────────────────────────────────
function idwValue(lat, lng, stations) {
  let num = 0, den = 0;
  for (const s of stations) {
    if (s.aqi == null) continue;
    const d = Math.hypot(lat - s.lat, lng - s.lon) + 1e-5;
    const w = 1 / (d * d);
    num += w * s.aqi;
    den += w;
  }
  return den > 0 ? num / den : null;
}

// ── Ward AQI now computed in useLiveData ──────────────────────────

const fmtPop = n => (n == null ? 'N/A' : Number(n).toLocaleString('en-IN'));
// Copy live ward names (from /api/wards) onto the ward polygons.
// Returns true if any name changed.
function applyLiveWardNames(geo, wardAqi) {
  let changed = false;
  geo?.features?.forEach(f => {
    const d = wardAqi?.[f.properties.wardCode];
    const liveName = d?.ward_name ?? d?.name;
    if (liveName && f.properties.wardName !== liveName) {
      f.properties.wardName = liveName;
      changed = true;
    }
  });
  return changed;
}
// ── Component ─────────────────────────────────────────────────────
export default function ShwasMap({
  layers,
  wardAqi = {},
  stationPoints,
  selectedStation,
  onStationClick,
  onClickEstimate,
  forecastOffset = 0,    // 0-23 hours; 0 = live
  allForecasts = null, // { [stationId]: forecast[] }
  windData = null, // { speed_mps, direction_deg, compass } | null
  firesData = null, // [{lat, lon, distance_km, frp_mw, upwind}] | null
  airMass = null,   // /api/attribution air_mass (back-trajectory) | null
  hotspots = [],   // [{lat, lon, ward_name, lcb, lcb_category}]
  sensorSites = [],   // [{lat, lon, ward_name, score, estimated_aqi}]
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const heatCanvasRef = useRef(null);   // offscreen canvas element
  const heatCtxRef = useRef(null);   // canvas 2d context
  const rafRef = useRef(null);   // pending requestAnimationFrame id
  const pinMarkerRef = useRef(null);   // click-estimate marker
  const popupRef = useRef(null);
  const initRef = useRef(false);
  const apiCacheRef = useRef(new Map());
  const styleReadyRef = useRef(false);
  const windMarkerRef = useRef(null);   // HTMLMarker for wind arrow
  const fireMarkersRef = useRef([]);     // array of HTMLMarkers for fires
  const airMassFitRef = useRef(null);    // last air_mass the camera was fitted to
  const hotspotMarkersRef = useRef([]);     // array of HTMLMarkers for LCB hotspots
  const sensorMarkersRef = useRef([]);     // array of HTMLMarkers for sensor sites

  // Always-current prop mirrors (safe inside async / RAF callbacks)
  const wardGeoRef = useRef(null);   // annotated ward GeoJSON (set once in onLoad)
  const stationPointsRef = useRef(stationPoints);
  const layersRef = useRef(layers);
  const allForecastsRef = useRef(allForecasts);
  const wardAqiRef = useRef(wardAqi);
  useEffect(() => { stationPointsRef.current = stationPoints; }, [stationPoints]);
  useEffect(() => { layersRef.current = layers; }, [layers]);
  useEffect(() => { allForecastsRef.current = allForecasts; }, [allForecasts]);
  useEffect(() => { wardAqiRef.current = wardAqi; }, [wardAqi]);

  const onStationClickRef = useRef(onStationClick);
  const onClickEstimateRef = useRef(onClickEstimate);
  useEffect(() => { onStationClickRef.current = onStationClick; }, [onStationClick]);
  useEffect(() => { onClickEstimateRef.current = onClickEstimate; }, [onClickEstimate]);

  const [unmatched, setUnmatched] = useState([]);

  // ── Initialise map once ──────────────────────────────────────
  useEffect(() => {
    if (initRef.current || !containerRef.current) return;
    initRef.current = true;

    let map;
    let fallbackUsed = false;

    function initMap(style) {
      map = new maplibregl.Map({
        container: containerRef.current,
        style,
        center: [72.878, 19.076],  // Mumbai central
        zoom: 11,                // tighter default
        minZoom: 10,
        maxZoom: 17,
        maxBounds: [         // restrict panning to Mumbai region
          [72.70, 18.85],             // SW corner
          [73.10, 19.35],             // NE corner
        ],
        pitchWithRotate: false,
        attributionControl: true,
      });
      mapRef.current = map;
      popupRef.current = new maplibregl.Popup({
        closeButton: false, closeOnClick: false,
        offset: 12, maxWidth: '240px', className: 'shwas-popup',
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
      map.on('load', () => onLoad(map));
      // Only fall back if the style itself fails to load (status errors),
      // not on expected warnings from setPaintProperty on non-existent layers.
      map.on('error', e => {
        const msg = e?.error?.message ?? '';
        const isStyleFailure = msg.includes('404') || msg.includes('fetch') || msg.includes('Failed to');
        if (!fallbackUsed && style !== ESRI_FALLBACK && isStyleFailure) {
          fallbackUsed = true;
          console.warn('[ShwasMap] style fetch failed, using Esri fallback');
          map.remove();
          initMap(ESRI_FALLBACK);
        }
      });
    }

    initMap(OFM_STYLE);
    return () => {
      initRef.current = false;
      map?.remove();
      mapRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Diagnostic: print heatmap status ────────────────────────────
  const diagnoseHeatmap = (map) => {
    try {
      const source = map.getSource('heatmap');
      const layer = map.getLayer('heatmap-layer');
      const style = map.getStyle();
      const layerOrder = style?.layers?.map(l => l.id) ?? [];
      const heatmapIdx = layerOrder.indexOf('heatmap-layer');

      console.group('[ShwasMap] Heatmap Diagnostics');
      console.log('Source exists:', !!source);
      console.log('Layer exists:', !!layer);
      if (layer) {
        console.log('Layer visibility:', map.getLayoutProperty('heatmap-layer', 'visibility'));
        console.log('Layer opacity (paint):', map.getPaintProperty('heatmap-layer', 'raster-opacity'));
        console.log('Layer resampling:', map.getPaintProperty('heatmap-layer', 'raster-resampling'));
      }
      console.log('Layer order index:', heatmapIdx, '/', layerOrder.length);
      console.log('Layers around heatmap:', layerOrder.slice(Math.max(0, heatmapIdx - 3), heatmapIdx + 3));
      console.groupEnd();
    } catch (e) {
      console.error('[ShwasMap] Diagnostics error:', e);
    }
  };

  // ── Heatmap drawing logic (smooth surface, clipped to wards) ───────
  // 1) IDW → opaque RGB pixels  2) blur  3) mask to ward polygons (one fill).
  const drawHeatmap = async (map, stations, wardGeoJSON, bounds) => {
    const canvas = heatCanvasRef.current;
    const ctx = heatCtxRef.current;
    if (!canvas || !ctx) return;

    const validStations = (stations ?? []).filter(s => s.aqi != null && s.aqi > 0);
    if (!validStations.length) return;
    if (!wardGeoJSON?.features?.length) return;

    const [[w, s], [e, n]] = bounds;
    const img = ctx.createImageData(SMOOTH_COLS, SMOOTH_ROWS);
    const px = img.data;
    let i = 0;
    for (let row = 0; row < SMOOTH_ROWS; row++) {
      const lat = n - (row + 0.5) / SMOOTH_ROWS * (n - s);
      for (let col = 0; col < SMOOTH_COLS; col++) {
        const lng = w + (col + 0.5) / SMOOTH_COLS * (e - w);
        const aqi = idwValue(lat, lng, validStations);
        const [r, g, b] = aqiRgb(aqi);
        px[i++] = r; px[i++] = g; px[i++] = b; px[i++] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);

    gaussianBlur(ctx, SMOOTH_COLS, SMOOTH_ROWS, 12);

    // Keep only pixels inside ward polygons
    ctx.save();
    ctx.globalCompositeOperation = 'destination-in';
    traceWardPath(ctx, wardGeoJSON, bounds);
    ctx.fillStyle = '#000';
    ctx.fill('evenodd');
    ctx.restore();

    map.triggerRepaint();
  };

  // ── After style loads ────────────────────────────────────────
  const onLoad = async (map) => {
    // 1 – Tint land + water (OFM positron layer ids)
    const tryPaint = (id, prop, val) => { try { map.setPaintProperty(id, prop, val); } catch { } };
    tryPaint('background', 'background-color', '#FCFEFC');
    tryPaint('water', 'fill-color', '#DCEBE2');
    ['water_shadow', 'water_pattern'].forEach(id => tryPaint(id, 'fill-color', '#DCEBE2'));
    ['landuse', 'landuse_overlay', 'national_park'].forEach(id => tryPaint(id, 'fill-color', '#FCFEFC'));

    // 2 – Load ward data
    let wardData;
    try {
      wardData = await loadWardData();
    } catch (err) {
      console.error('[ShwasMap] ward data failed:', err);
      return;
    }
    const { geojson, bounds, unmatched: um } = wardData;
    wardGeoRef.current = geojson;
    setUnmatched(um);
    styleReadyRef.current = true;

    // 3 – fitBounds to Mumbai wards
    map.fitBounds(bounds, {
      padding: { top: 40, left: 40, right: 40, bottom: 40 }, // bottom room for the slider
      duration: 0,
      maxZoom: 12,
    });
    const [[w, s], [e, n]] = bounds;
    // Clamp panning to just around Mumbai (ward bounds + small buffer)
    map.setMaxBounds([[w - 0.05, s - 0.12], [e + 0.05, n + 0.05]]);

    // 4 – Build smooth heatmap canvas source ─────────────────────────
    const heatCanvas = document.createElement('canvas');
    heatCanvas.width = SMOOTH_COLS;
    heatCanvas.height = SMOOTH_ROWS;
    heatCanvasRef.current = heatCanvas;
    const ctx = heatCanvas.getContext('2d');
    heatCtxRef.current = ctx;

    // Initial draw (IDW + blur, clipped to wards)
    await drawHeatmap(map, stationPointsRef.current ?? [], geojson, [[GEO.W, GEO.S], [GEO.E, GEO.N]]);

    // Add canvas source + raster layer
    map.addSource('heatmap', {
      type: 'canvas', canvas: heatCanvas,
      coordinates: HEAT_COORDS,
      animate: true,
    });

    // Insert heatmap layer BEFORE first symbol layer (so labels stay readable)
    // and ABOVE all fill layers (basemap land, landcover, park, water, etc.)
    const style = map.getStyle();
    const layersArr = style.layers;
    const symbolIdx = layersArr.findIndex(l => l.type === 'symbol');
    // Find last fill/raster layer before first symbol (to insert above all fills)
    let insertBefore = undefined;
    if (symbolIdx >= 0) {
      insertBefore = layersArr[symbolIdx].id;
    } else {
      // Fallback: insert before first fill layer from the end (topmost fill)
      const lastFillIdx = [...layersArr].reverse().findIndex(l => l.type === 'fill' || l.type === 'raster');
      if (lastFillIdx >= 0) {
        insertBefore = layersArr[layersArr.length - 1 - lastFillIdx].id;
      }
    }

    map.addLayer({
      id: 'heatmap-layer',
      type: 'raster',
      source: 'heatmap',
      layout: { visibility: layersRef.current.heatmap ? 'visible' : 'none' },
      paint: {
        'raster-opacity': 0.25,
        'raster-resampling': 'linear',
      },
    }, insertBefore);

    map.triggerRepaint();
    diagnoseHeatmap(map);
    applyLiveWardNames(geojson, wardAqiRef.current);

    // 5 – Ward source + layers ───────────────────────────────
    map.addSource('wards', {
      type: 'geojson', data: geojson, promoteId: 'wardCode',
    });

    // Ward AQI choropleth (above basemap land, below outlines)
    map.addLayer({
      id: 'wards-aqi',
      type: 'fill',
      source: 'wards',
      layout: { visibility: layersRef.current.heatmap ? 'visible' : 'none' },
      paint: {
        'fill-color': [
          'match',
          ['get', 'wardCode'],
          '__dummy__', 'transparent',
          ...Object.entries(wardAqiRef.current).flatMap(([code, data]) => [
            code, getAQIColor(data.aqi)
          ]),
          '#CCCCCC'
        ],
        'fill-opacity': 0.25,
        'fill-translate': [0, 0],
      },
    }, insertBefore);

    // Population choropleth (hidden by default)
    const popVals = geojson.features.map(f => f.properties.population ?? 0).sort((a, b) => a - b).filter(v => v > 0);
    const q = i => popVals[Math.min(Math.floor((i / 5) * popVals.length), popVals.length - 1)] || 0;
    map.addLayer({
      id: 'wards-pop', type: 'fill', source: 'wards',
      layout: { visibility: 'none' },
      paint: {
        'fill-color': ['interpolate', ['linear'], ['get', 'population'],
          q(0), '#F3E5F5', q(1), '#E1BEE7', q(2), '#CE93D8',
          q(3), '#AB47BC', q(4), '#8E24AA', q(5), '#4A148C',
        ],
        'fill-opacity': 0.45,
      },
    }, insertBefore);

    // Slum clusters
    map.addSource('slums', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({
      id: 'slums-fill', type: 'fill', source: 'slums',
      layout: { visibility: 'none' },
      paint: { 'fill-color': '#6FA287', 'fill-opacity': 0.35 },
    }, insertBefore);

    // Ward hover fill + outline
    map.addLayer({
      id: 'wards-hover', type: 'fill', source: 'wards',
      layout: { visibility: layersRef.current.boundaries ? 'visible' : 'none' },
      paint: {
        'fill-color': '#DDEBE2',
        'fill-opacity': ['case', ['boolean', ['feature-state', 'hovered'], false], 0.40, 0],
      },
    }, insertBefore);
    map.addLayer({
      id: 'wards-hover-outline',
      type: 'line',
      source: 'wards',
      layout: { visibility: layersRef.current.boundaries ? 'visible' : 'none' },
      paint: {
        'line-color': '#DDEBE2',
        'line-width': ['case', ['boolean', ['feature-state', 'hovered'], false], 2.5, 0],
        'line-opacity': ['case', ['boolean', ['feature-state', 'hovered'], false], 0.9, 0],
      },
    }, insertBefore);

    // Ward outlines
    map.addLayer({
      id: 'wards-line', type: 'line', source: 'wards',
      layout: { visibility: layersRef.current.boundaries ? 'visible' : 'none' },
      paint: { 'line-color': '#2C4A3A', 'line-width': 2, 'line-opacity': 1 },
    }, insertBefore);

    // Ward labels at centroids
    map.addLayer({
      id: 'wards-labels',
      type: 'symbol',
      source: 'wards',
      minzoom: 11,
      layout: {
        visibility: layersRef.current.boundaries ? 'visible' : 'none',
        'text-field': ['get', 'wardName'],
        'text-font': ['Noto Sans Regular'],
        'text-size': 11,
        'text-anchor': 'center',
        'text-allow-overlap': false,
        'text-ignore-placement': false,
      },
      paint: {
        'text-color': '#17241E',
        'text-halo-color': '#FFFFFF',
        'text-halo-width': 2.5,
        'text-halo-blur': 0,
      },
    });

    // 6 – Station layers ─────────────────────────────────────
    map.addSource('stations', { type: 'geojson', data: buildStationFC(stationPointsRef.current ?? []) });

    // Selection ring
    map.addLayer({
      id: 'stations-ring', type: 'circle', source: 'stations',
      filter: ['==', ['get', 'id'], ''],
      paint: {
        'circle-radius': 16,
        'circle-color': 'transparent',
        'circle-stroke-width': 2.5,
        'circle-stroke-color': ['get', 'color'],
        'circle-stroke-opacity': 0.55,
      },
    });

    // Station circles — 28px diameter = radius 14, with white border + shadow
    map.addLayer({
      id: 'stations-circle', type: 'circle', source: 'stations',
      layout: { visibility: layersRef.current.stations ? 'visible' : 'none' },
      paint: {
        'circle-radius': 14,
        'circle-color': ['get', 'color'],
        'circle-stroke-width': 3,
        'circle-stroke-color': '#ffffff',
      },
      // Show top 10 worst + 5 best at zoom < 11, all at zoom >= 11
      filter: [
        'any',
        ['>=', ['zoom'], 11],
        ['in', ['get', 'id'], ['literal', []]]  // placeholder, updated dynamically
      ],
    });

    // Station AQI numbers — white, bold, 11px, above circles
    map.addLayer({
      id: 'stations-labels',
      type: 'symbol',
      source: 'stations',
      layout: {
        visibility: layersRef.current.stations ? 'visible' : 'none',
        'text-field': ['get', 'aqi'],
        'text-font': ['Noto Sans Bold'],
        'text-size': 11,
        'text-anchor': 'center',
        'text-allow-overlap': true,
        'text-ignore-placement': true,
      },
      paint: {
        'text-color': '#FFFFFF',
        'text-halo-color': '#000000',
        'text-halo-width': 1,
        'text-halo-blur': 0,
      },
      // Same zoom filter as circles
      filter: [
        'any',
        ['>=', ['zoom'], 11],
        ['in', ['get', 'id'], ['literal', []]]
      ],
    });

    // Air-mass back-trajectory: under the station circles, above everything else
    addAirMassLayers(map, 'stations-ring');

    // 7 – Ward hover interactions ─────────────────────────────
    // AQI is computed live at the hovered point via IDW, so it always
    // reflects current station data even if stations loaded after map init.
    let hoveredId = null;
    let hoverTimeout = null;

    // (removed local stationCounts)

    map.on('mousemove', 'wards-hover', e => {
      if (!e.features?.length) return;
      const feat = e.features[0];
      const id = feat.properties.wardCode;
      if (hoveredId && hoveredId !== id)
        map.setFeatureState({ source: 'wards', id: hoveredId }, { hovered: false });
      hoveredId = id;
      map.setFeatureState({ source: 'wards', id }, { hovered: true });
      map.getCanvas().style.cursor = 'crosshair';

      const pop = feat.properties.population;
      const wardData = wardAqiRef.current[id] || {};
      const aqi = wardData.aqi;
      const cat = aqi != null ? getCategory(aqi) : null;
      const count = wardData.count || 0;
      const estimated = wardData.estimated || false;
      // Show ward name: prefer wardName from API, then geojson, then code
      const wName = wardData.ward_name ?? feat.properties.wardName ?? id ?? '';
      const wLabel = wName !== id ? `${wName} (${id})` : wName;

      // Clear any pending remove to prevent flicker
      if (hoverTimeout) { clearTimeout(hoverTimeout); hoverTimeout = null; }

      popupRef.current.setLngLat(e.lngLat).setHTML(`
        <div class="shwas-popup-inner shwas-ward-tooltip">
          <div class="shwas-popup-name">${wLabel}</div>
          <div class="shwas-popup-pop">Population: ${fmtPop(pop)}</div>
          ${aqi != null
          ? `<div class="shwas-popup-aqi" style="color:${cat.color}">
                 <span class="aqi-chip" style="background:${cat.color}">${aqi}</span>
                 <span class="shwas-popup-cat">${cat.label}</span>
               </div>`
          : `<div class="shwas-popup-aqi shwas-popup-nodata">AQI: No data</div>`}
          <div class="shwas-popup-stations">
            ${count > 0 ? `${count} station${count > 1 ? 's' : ''} in this ward` : (estimated ? 'Estimated' : 'No live data')}
          </div>
        </div>`).addTo(map);
    });

    map.on('mouseleave', 'wards-hover', () => {
      if (hoveredId) {
        map.setFeatureState({ source: 'wards', id: hoveredId }, { hovered: false });
        hoveredId = null;
      }
      map.getCanvas().style.cursor = '';
      // Delay removal to prevent flicker when moving between features
      hoverTimeout = setTimeout(() => {
        popupRef.current.remove();
        hoverTimeout = null;
      }, 80);
    });

    // 8 – Station hover + click ──────────────────────────────
    let stationHoverTimeout = null;
    map.on('mouseenter', 'stations-circle', e => {
      if (!e.features?.length) return;
      map.getCanvas().style.cursor = 'pointer';
      const p = e.features[0].properties;
      const readingTime = p.updated_at ? new Date(p.updated_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' }) : 'Live';

      if (stationHoverTimeout) { clearTimeout(stationHoverTimeout); stationHoverTimeout = null; }

      popupRef.current.setLngLat(e.lngLat).setHTML(`
        <div class="shwas-popup-inner shwas-station-tooltip">
          <div class="shwas-popup-name">${p.name}</div>
          <div class="shwas-popup-sub">${[p.agency, p.ward ? 'Ward ' + p.ward : null].filter(Boolean).join(' · ')}</div>
          <div class="shwas-popup-aqi" style="color:${p.color}">
            <span class="aqi-chip" style="background:${p.color}">${p.aqi}</span>
            <span class="shwas-popup-cat">${getCategory(p.aqi).label}</span>
          </div>
          <div class="shwas-popup-pollutants">
            <span>PM2.5: ${p.pm25 ?? '—'} µg/m³</span>
            <span>PM10: ${p.pm10 ?? '—'} µg/m³</span>
          </div>
          <div class="shwas-popup-time">Updated ${readingTime}</div>
        </div>`).addTo(map);
    });
    map.on('mouseleave', 'stations-circle', () => {
      map.getCanvas().style.cursor = '';
      stationHoverTimeout = setTimeout(() => {
        popupRef.current.remove();
        stationHoverTimeout = null;
      }, 80);
    });
    map.on('click', 'stations-circle', e => {
      e.originalEvent.stopPropagation();
      if (!e.features?.length) return;
      onStationClickRef.current?.(e.features[0].properties);
      popupRef.current.remove();
    });

    // 9 – Map click for estimate ──────────────────────────────
    map.on('click', async e => {
      const { lng, lat } = e.lngLat;
      // A click on a station circle selects that station (handled above)
      if (map.queryRenderedFeatures(e.point, { layers: ['stations-circle'] }).length) return;
      // Only respond if click is on land (inside a ward polygon)
      const wardFeatures = wardGeoRef.current?.features ?? [];
      if (!isLand(lng, lat, wardFeatures)) return;
      popupRef.current.remove();

      // Drop dashed pin
      placeDashedPin(map, lng, lat);

      // Fetch estimate
      try {
        const cacheKey = `${lat.toFixed(4)},${lng.toFixed(4)}`;
        let data = apiCacheRef.current.get(cacheKey);
        if (!data) {
          data = await apiInterpolate(lat, lng);
          apiCacheRef.current.set(cacheKey, data);
        }

        // If a real station is within 1.5 km, use its measured AQI so the
        // right-panel value matches the station bubble the user sees on the map.
        const pts = stationPointsRef.current ?? [];
        const kx = Math.cos((lat * Math.PI) / 180);
        let nearestDist = Infinity, nearestStation = null;
        for (const s of pts) {
          if (s.aqi == null || s.lat == null || s.lon == null) continue;
          const distKm = Math.hypot((s.lon - lng) * kx, s.lat - lat) * 111;
          if (distKm < nearestDist) { nearestDist = distKm; nearestStation = s; }
        }
        const snapped = nearestStation && nearestDist <= 1.5;
        onClickEstimateRef.current?.({
          ...data,
          lat,
          lon: lng,
          estimated_aqi: snapped ? nearestStation.aqi : data.estimated_aqi,
        });
      } catch {
        // Fallback: IDW from current station data
        const pts = stationPointsRef.current ?? [];
        const v = idwValue(lat, lng, pts);
        onClickEstimateRef.current?.({
          lat, lon: lng,
          estimated_aqi: v ?? 0,
          model: 'idw',
          stations_used: pts.length,
        });
      }

    });
  };

  // ── Helpers ──────────────────────────────────────────────────
  function buildStationFC(pts) {
    return {
      type: 'FeatureCollection',
      features: (pts ?? []).filter(s => s.aqi != null).map(s => ({
        type: 'Feature',
        properties: {
          id: s.id, name: s.name, agency: s.agency,
          ward: s.ward, aqi: s.aqi, color: getAQIColor(s.aqi),
          pm25: s.pm25 ?? null, pm10: s.pm10 ?? null,
          updated_at: s.updated_at ?? null,
        },
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
      })),
    };
  }

  /** Return stations with AQI values at the given forecast offset (0 = live). */
  function getStationsAtOffset(stations, fcMap, offset) {
    if (!offset || !fcMap) return stations;
    return stations.map(s => {
      const fc = fcMap[s.id];
      const idx = Math.min(offset, (fc?.length ?? 0) - 1);
      const raw = idx >= 0 ? fc[idx]?.aqi : null;
      // missing or 0 means "no forecast", so keep the live value
      const aqi = raw != null && raw > 0 ? Math.round(raw) : s.aqi;
      return { ...s, aqi };
    });
  }

  function placeDashedPin(map, lng, lat) {
    // Remove previous pin
    pinMarkerRef.current?.remove();
    const el = document.createElement('div');
    el.className = 'estimate-pin';
    pinMarkerRef.current = new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat([lng, lat])
      .addTo(map);
  }

  // ── Slum lazy-load ───────────────────────────────────────────
  const slumLoaded = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    if (layers.slums && !slumLoaded.current) {
      slumLoaded.current = true;
      fetch('/data/slumClusters.geojson')
        .then(r => r.json())
        .then(d => { if (map.getSource('slums')) map.getSource('slums').setData(d); })
        .catch(e => console.warn('[ShwasMap] slums:', e));
    }
  }, [layers.slums]);

  // ── Layer visibility ─────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    const vis = (id, on) => { try { map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'); } catch { } };
    vis('stations-circle', layers.stations);
    vis('stations-ring', layers.stations);
    vis('stations-labels', layers.stations);
    vis('wards-line', layers.boundaries);
    vis('wards-hover', layers.boundaries);
    vis('wards-hover-outline', layers.boundaries);
    vis('wards-labels', layers.boundaries);
    vis('wards-pop', layers.population);
    vis('slums-fill', layers.slums);
    vis('heatmap-layer', layers.heatmap);
    vis('wards-aqi', layers.heatmap);
  }, [layers]);

  // ── Update station GeoJSON ───────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    const src = map.getSource('stations');
    if (src) src.setData(buildStationFC(stationPoints ?? []));

    // Update zoom-based filter: top 10 worst + 5 best at zoom < 11
    const valid = (stationPoints ?? []).filter(s => s.aqi != null && s.aqi > 0);
    if (valid.length) {
      const sorted = [...valid].sort((a, b) => b.aqi - a.aqi);
      const worst10 = sorted.slice(0, 10).map(s => s.id);
      const best5 = sorted.slice(-5).map(s => s.id);
      const showIds = [...new Set([...worst10, ...best5])];
      const filter = ['any', ['>=', ['zoom'], 11], ['in', ['get', 'id'], ['literal', showIds]]];
      try { map.setFilter('stations-circle', filter); } catch { }
      try { map.setFilter('stations-labels', filter); } catch { }
    }
  }, [stationPoints]);

  // ── Redraw heatmap when live station data arrives ────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    // Only redraw if we have actual AQI data (not the initial static seed)
    const hasRealData = (stationPoints ?? []).some(s => s.aqi != null);
    if (hasRealData) {
      const b = [[GEO.W, GEO.S], [GEO.E, GEO.N]];
      drawHeatmap(map, stationPoints ?? [], wardGeoRef.current ?? { type: 'FeatureCollection', features: [] }, b);
      diagnoseHeatmap(map);
    }
  }, [stationPoints]);

  // ── Update ward AQI choropleth when station data changes ──────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;

    if (applyLiveWardNames(wardGeoRef.current, wardAqi)) {
      map.getSource('wards')?.setData(wardGeoRef.current);
    }
    const colorStops = Object.entries(wardAqi).flatMap(([code, data]) => [code, getAQIColor(data.aqi)]);
    if (colorStops.length) {
      try {
        map.setPaintProperty('wards-aqi', 'fill-color', [
          'match', ['get', 'wardCode'], ...colorStops, '#CCCCCC'
        ]);
      } catch { }
    } else {
      try {
        map.setPaintProperty('wards-aqi', 'fill-color', '#CCCCCC');
      } catch { }
    }
  }, [wardAqi]);

  // ── Selected station highlight ───────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    try { map.setFilter('stations-ring', ['==', ['get', 'id'], selectedStation?.id || '']); } catch { }
    if (selectedStation?.lon != null) {
      map.easeTo({ center: [selectedStation.lon, selectedStation.lat], zoom: Math.max(map.getZoom(), 12), duration: 600 });
      pinMarkerRef.current?.remove();
      pinMarkerRef.current = null;
    }
  }, [selectedStation]);

  // ── Time slider — recolour stations + heatmap ────────────────
  // All work is synchronous (client-side IDW); use RAF to coalesce
  // rapid slider drags into a single repaint per frame.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;

    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    rafRef.current = requestAnimationFrame(() => {
      const offset = forecastOffset ?? 0;
      const fcMap = allForecastsRef.current;
      const stations = stationPointsRef.current ?? [];
      const adjusted = getStationsAtOffset(stations, fcMap, offset);

      // 1. Recolour station circles
      const src = map.getSource('stations');
      if (src) src.setData(buildStationFC(adjusted));

      // 2. Recolour heatmap canvas (smooth surface, clipped to wards)
      const wardsSource = map.getSource('wards');
      const b = [[GEO.W, GEO.S], [GEO.E, GEO.N]];

      const currentWardGeoJSON = wardGeoRef.current ?? { type: 'FeatureCollection', features: [] };
      drawHeatmap(map, adjusted, currentWardGeoJSON, b);

      // 3. Recolour wards choropleth
      if (wardsSource) {
        const wardAQI = offset > 0 ? computeWardAqi(currentWardGeoJSON, adjusted) : wardAqiRef.current;
        const colorStops = Object.entries(wardAQI).flatMap(([code, data]) => [code, getAQIColor(data.aqi)]);
        if (colorStops.length) {
          try {
            map.setPaintProperty('wards-aqi', 'fill-color', [
              'match', ['get', 'wardCode'], ...colorStops, '#CCCCCC'
            ]);
          } catch { }
        } else {
          try {
            map.setPaintProperty('wards-aqi', 'fill-color', '#CCCCCC');
          } catch { }
        }
      }
    });

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [forecastOffset, allForecasts, stationPoints]); // eslint-disable-line react-hooks/exhaustive-deps // eslint-disable-line react-hooks/exhaustive-deps

  // ── Wind arrow marker ────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    windMarkerRef.current?.remove();
    windMarkerRef.current = null;

    const coord = selectedStation ?? null;
    if (!map || !styleReadyRef.current || !windData || !coord || !layers.windFires) return;

    const { speed_mps, direction_deg } = windData;
    // Arrow rotated so it points in the wind direction (arrow points "to", meteorologically "from" is 180° flip)
    const rotate = ((direction_deg ?? 0) + 180) % 360;

    const el = document.createElement('div');
    el.className = 'wind-marker';
    el.setAttribute('aria-label', `Wind ${speed_mps?.toFixed(1)} m/s from ${direction_deg}°`);
    el.innerHTML = `
      <div class="wind-marker__arrow">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
             stroke="var(--forest)" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round"
             style="transform:rotate(${rotate}deg);display:block">
          <path d="M12 3 L12 21 M12 3 L7 9 M12 3 L17 9"/>
        </svg>
      </div>
      <div class="wind-marker__speed">${speed_mps?.toFixed(1)} m/s</div>
    `;

    windMarkerRef.current = new maplibregl.Marker({ element: el, anchor: 'center', offset: [32, 0] })
      .setLngLat([coord.lon, coord.lat])
      .addTo(map);
  }, [windData, selectedStation, layers.windFires]);

  // ── Hotspot markers ──────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    hotspotMarkersRef.current.forEach(m => m.remove());
    hotspotMarkersRef.current = [];
    if (!map || !styleReadyRef.current || !hotspots?.length || !layers.hotspots) return;

    hotspots.forEach(h => {
      if (h.lat == null || h.lon == null) return;
      const el = document.createElement('div');
      el.className = 'hotspot-marker';
      const info = describeHotspot(h);
      el.setAttribute('aria-label', `Hotspot: ${info.title}`);
      el.innerHTML = `
        <div class="hotspot-marker__pulse"></div>
        <div class="hotspot-marker__core" title="${info.title}">
          <div class="hotspot-marker__aqi">${info.aqi}</div>
          <div class="hotspot-marker__label">${info.category}</div>
        </div>
      `;
      const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat([h.lon, h.lat])
        .addTo(map);
      hotspotMarkersRef.current.push(marker);
    });
  }, [hotspots, layers.hotspots]);

  // ── Sensor site markers ──────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    sensorMarkersRef.current.forEach(m => m.remove());
    sensorMarkersRef.current = [];
    if (!map || !styleReadyRef.current || !sensorSites?.length || !layers.sensors) return;

    sensorSites.forEach((s, idx) => {
      if (s.lat == null || s.lon == null) return;
      const el = document.createElement('div');
      el.className = 'sensor-marker';
      el.setAttribute('aria-label', `Recommended sensor #${idx + 1}: ${s.ward_name ?? ''}`);
      el.innerHTML = `
        <div class="sensor-marker__ring"></div>
        <div class="sensor-marker__body" title="${s.ward_name ?? ''}: ${s.reason === 'unmonitored_ward' ? 'no station in this ward · ' : ''}gap score ${s.score?.toFixed(2) ?? ''}">
          <div class="sensor-marker__rank">#${idx + 1}</div>
          <div class="sensor-marker__label">${s.ward_name?.split(' ')[0] ?? 'Ward'}</div>
        </div>
      `;
      const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat([s.lon, s.lat])
        .addTo(map);
      sensorMarkersRef.current.push(marker);
    });
  }, [sensorSites, layers.sensors]);

  // ── Fire markers ─────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    // Always remove old fire markers first
    fireMarkersRef.current.forEach(m => m.remove());
    fireMarkersRef.current = [];

    if (!map || !styleReadyRef.current || !firesData?.length || !layers.windFires) return;

    firesData.forEach(fire => {
      if (fire.lat == null || fire.lon == null) return;
      const el = document.createElement('div');
      el.className = fire.upwind ? 'fire-marker fire-marker--upwind' : 'fire-marker';
      el.setAttribute('aria-label', `Fire ${fire.distance_km ?? '?'} km away${fire.upwind ? ', upwind of the station' : ''}`);
      const mw = fire.frp_mw != null ? `${Number(fire.frp_mw).toFixed(1)}MW` : '';
      const km = fire.distance_km != null ? `${fire.distance_km}km` : '';
      el.innerHTML = `
        <div class="fire-marker__triangle"></div>
        <div class="fire-marker__label">${[fire.upwind ? 'upwind' : '', km, mw].filter(Boolean).join(' · ')}</div>
      `;
      const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
        .setLngLat([fire.lon, fire.lat])
        .addTo(map);
      fireMarkersRef.current.push(marker);
    });
  }, [firesData, layers.windFires]);

  // Air-mass back-trajectory: draw the path and, when it runs off screen, zoom out to show it
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    const visible = setAirMass(map, airMass, Boolean(layers.windFires));
    const bounds = airMassBounds(airMass);
    if (visible && bounds && airMassFitRef.current !== airMass) {
      airMassFitRef.current = airMass;
      const origin = airMass.origin;
      if (!map.getBounds().contains([origin.lon, origin.lat])) {
        map.fitBounds(bounds, {
          padding: { top: 100, bottom: 120, left: 60, right: 60 },
          maxZoom: 11,
          duration: 700,
        });
      }
    }
  }, [airMass, layers.windFires]);

  return (
    <div className="shwas-map-wrap">
      <div ref={containerRef} className="shwas-map-canvas" />

      {layers.hotspots && Array.isArray(hotspots) && hotspots.length === 0 && (
        <div className="hotspot-empty" role="status">
          No hotspots above AQI 100 right now
        </div>
      )}

      {unmatched.length > 0 && (
        <div className="shwas-dev-banner">
          Dev: {unmatched.length} ward(s) not joined: <strong>{unmatched.join(', ')}</strong>
        </div>
      )}
    </div>
  );
}