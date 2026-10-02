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
import { getAQIColor, getCategory } from '../utils/aqi';
import { interpolate as apiInterpolate } from '../utils/api';
import './ShwasMap.css';

// ── Geographic constants ──────────────────────────────────────────
const GEO = { W: 72.75, E: 73.02, S: 18.88, N: 19.30 };

// ── Heatmap grid ──────────────────────────────────────────────────
// Smooth surface: ~400x520 canvas, clipped to ward polygons, blurred
const SMOOTH_COLS = 400, SMOOTH_ROWS = 520;
const dLng = (GEO.E - GEO.W) / SMOOTH_COLS;
const dLat = (GEO.N - GEO.S) / SMOOTH_ROWS;
const CONCURRENCY = 12;

// MapLibre canvas-source corner coordinates (clockwise from top-left)
const HEAT_COORDS = [
  [GEO.W, GEO.N],
  [GEO.E, GEO.N],
  [GEO.E, GEO.S],
  [GEO.W, GEO.S],
];

// ── Gaussian blur (separable, 6px sigma) ──────────────────────────
function gaussianBlur(ctx, width, height, sigma = 6) {
  const radius = Math.ceil(sigma * 3);
  const kernel = [];
  let sum = 0;
  for (let x = -radius; x <= radius; x++) {
    const w = Math.exp(-(x * x) / (2 * sigma * sigma));
    kernel.push({ x, w });
    sum += w;
  }
  kernel.forEach(k => k.w /= sum);

  const src = ctx.getImageData(0, 0, width, height);
  const tmp = new ImageData(width, height);
  const dst = ctx.createImageData(width, height);
  const sd = src.data, td = tmp.data, dd = dst.data;

  // Horizontal pass
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      kernel.forEach(k => {
        const sx = Math.min(Math.max(x + k.x, 0), width - 1);
        const i = (y * width + sx) * 4;
        r += sd[i] * k.w;
        g += sd[i + 1] * k.w;
        b += sd[i + 2] * k.w;
        a += sd[i + 3] * k.w;
      });
      const o = (y * width + x) * 4;
      td[o] = r; td[o + 1] = g; td[o + 2] = b; td[o + 3] = a;
    }
  }

  // Vertical pass
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      kernel.forEach(k => {
        const sy = Math.min(Math.max(y + k.x, 0), height - 1);
        const i = (sy * width + x) * 4;
        r += td[i] * k.w;
        g += td[i + 1] * k.w;
        b += td[i + 2] * k.w;
        a += td[i + 3] * k.w;
      });
      const o = (y * width + x) * 4;
      dd[o] = r; dd[o + 1] = g; dd[o + 2] = b; dd[o + 3] = a;
    }
  }

  ctx.putImageData(dst, 0, 0);
}

// ── Draw ward polygon paths on canvas for clipping ────────────────
function drawWardClip(ctx, wardsGeoJSON, bounds) {
  if (!wardsGeoJSON?.features?.length) return;
  const [[w, s], [e, n]] = bounds;
  const scaleX = SMOOTH_COLS / (e - w);
  const scaleY = SMOOTH_ROWS / (n - s);
  
  ctx.beginPath();
  wardsGeoJSON.features.forEach(feat => {
    const coords = feat.geometry.coordinates;
    if (feat.geometry.type === 'Polygon') {
      coords.forEach(ring => {
        ring.forEach(([lng, lat], i) => {
          const x = (lng - w) * scaleX;
          const y = (n - lat) * scaleY; // flip Y
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.closePath();
      });
    } else if (feat.geometry.type === 'MultiPolygon') {
      coords.forEach(poly => {
        poly.forEach(ring => {
          ring.forEach(([lng, lat], i) => {
            const x = (lng - w) * scaleX;
            const y = (n - lat) * scaleY;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          });
          ctx.closePath();
        });
      });
    }
  });
  ctx.clip();
}

// ── Styles ────────────────────────────────────────────────────────
const OFM_STYLE    = 'https://tiles.openfreemap.org/styles/positron';
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
    { id: 'esri-base',   type: 'raster', source: 'esri',     minzoom: 0, maxzoom: 22 },
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

// ── Canvas helpers ────────────────────────────────────────────────
function drawCell(ctx, col, row, aqi) {
  ctx.fillStyle = getAQIColor(aqi);
  // Row 0 = southernmost lat → canvas bottom = ROWS-1-0 = ROWS-1
  ctx.fillRect(col, ROWS - 1 - row, 1, 1);
}

// ── Concurrent batch runner ───────────────────────────────────────
async function runConcurrent(tasks, limit, onEach) {
  const queue = [...tasks];
  async function worker() {
    while (queue.length) {
      const task = queue.shift();
      await onEach(task);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, tasks.length) }, worker));
}

// ── Ward AQI now computed in useLiveData ──────────────────────────

const fmtPop  = n => (n == null ? 'N/A' : Number(n).toLocaleString('en-IN'));

// ── Component ─────────────────────────────────────────────────────
export default function ShwasMap({
  layers,
  wardAqi = {},
  stationPoints,
  selectedStation,
  onStationClick,
  onClickEstimate,
  forecastOffset = 0,    // 0-23 hours; 0 = live
  allForecasts   = null, // { [stationId]: forecast[] }
  windData       = null, // { speed_mps, direction_deg, compass } | null
  firesData      = null, // [{lat, lon, distance_km, intensity_mw}] | null
}) {
  const containerRef        = useRef(null);
  const mapRef              = useRef(null);
  const heatCanvasRef       = useRef(null);   // offscreen canvas element
  const heatCtxRef          = useRef(null);   // canvas 2d context
  const landCellsRef        = useRef([]);     // land-only grid cells (computed once)
  const originalPixelsRef   = useRef(null);   // ImageData snapshot after GNN pass
  const rafRef              = useRef(null);   // pending requestAnimationFrame id
  const pinMarkerRef        = useRef(null);   // click-estimate marker
  const popupRef            = useRef(null);
  const initRef             = useRef(false);
  const apiCacheRef         = useRef(new Map());
  const styleReadyRef       = useRef(false);
  const windMarkerRef       = useRef(null);   // HTMLMarker for wind arrow
  const fireMarkersRef      = useRef([]);     // array of HTMLMarkers for fires

  // Always-current prop mirrors (safe inside async / RAF callbacks)
  const stationPointsRef   = useRef(stationPoints);
  const layersRef          = useRef(layers);
  const allForecastsRef    = useRef(allForecasts);
  const wardAqiRef         = useRef(wardAqi);
  useEffect(() => { stationPointsRef.current = stationPoints; }, [stationPoints]);
  useEffect(() => { layersRef.current        = layers;         }, [layers]);
  useEffect(() => { allForecastsRef.current  = allForecasts;   }, [allForecasts]);
  useEffect(() => { wardAqiRef.current       = wardAqi;        }, [wardAqi]);

  const onStationClickRef  = useRef(onStationClick);
  const onClickEstimateRef = useRef(onClickEstimate);
  useEffect(() => { onStationClickRef.current  = onStationClick;  }, [onStationClick]);
  useEffect(() => { onClickEstimateRef.current = onClickEstimate; }, [onClickEstimate]);

  const [unmatched, setUnmatched] = useState([]);
  const [heatLoading, setHeatLoading] = useState(false);

  // ── Initialise map once ──────────────────────────────────────
  useEffect(() => {
    if (initRef.current || !containerRef.current) return;
    initRef.current = true;

    let map;
    let fallbackUsed = false;

    function initMap(style) {
      map = new maplibregl.Map({
        container:          containerRef.current,
        style,
        center:             [72.878, 19.076],  // Mumbai central
        zoom:               11,                // tighter default
        minZoom:            10,
        maxZoom:            17,
        maxBounds:          [         // restrict panning to Mumbai region
          [72.70, 18.85],             // SW corner
          [73.10, 19.35],             // NE corner
        ],
        pitchWithRotate:    false,
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
  const drawHeatmap = async (map, stations, wardGeoJSON, bounds) => {
    const canvas = heatCanvasRef.current;
    const ctx = heatCtxRef.current;
    if (!canvas || !ctx) return;

    const validStations = (stations ?? []).filter(s => s.aqi != null && s.aqi > 0);
    if (!validStations.length) return;

    // Clear canvas
    ctx.clearRect(0, 0, SMOOTH_COLS, SMOOTH_ROWS);

    // Clip to ward polygons
    ctx.save();
    drawWardClip(ctx, wardGeoJSON, bounds);
    ctx.clip();

    // Render IDW (power 2) to canvas
    const [[w, s], [e, n]] = bounds;
    for (let col = 0; col < SMOOTH_COLS; col++) {
      for (let row = 0; row < SMOOTH_ROWS; row++) {
        const lng = w + (col + 0.5) / SMOOTH_COLS * (e - w);
        const lat = n - (row + 0.5) / SMOOTH_ROWS * (n - s);
        const aqi = idwValue(lat, lng, validStations);
        if (aqi != null) {
          ctx.fillStyle = getAQIColor(aqi);
          ctx.fillRect(col, row, 1, 1);
        }
      }
    }
    ctx.restore();

    // Gaussian blur
    gaussianBlur(ctx, SMOOTH_COLS, SMOOTH_ROWS, 12);

    map.triggerRepaint();
  };

  // ── After style loads ────────────────────────────────────────
  const onLoad = async (map) => {
    // 1 – Tint land + water (OFM positron layer ids)
    const tryPaint = (id, prop, val) => { try { map.setPaintProperty(id, prop, val); } catch {} };
    tryPaint('background', 'background-color', '#FCFEFC');
    tryPaint('water',      'fill-color',       '#DCEBE2');
    ['water_shadow','water_pattern'].forEach(id => tryPaint(id, 'fill-color', '#DCEBE2'));
    ['landuse','landuse_overlay','national_park'].forEach(id => tryPaint(id, 'fill-color', '#FCFEFC'));

    // 2 – Load ward data
    let wardData;
    try {
      wardData = await loadWardData();
    } catch (err) {
      console.error('[ShwasMap] ward data failed:', err);
      return;
    }
    const { geojson, bounds, unmatched: um } = wardData;
    setUnmatched(um);
    styleReadyRef.current = true;

    // 3 – fitBounds to Mumbai wards
    map.fitBounds(bounds, { padding: 32, duration: 800, maxZoom: 12 });
    const [[w, s], [e, n]] = bounds;
    // Clamp panning to just around Mumbai (ward bounds + small buffer)
    map.setMaxBounds([[w - 0.05, s - 0.05], [e + 0.05, n + 0.05]]);

    // 4 – Build smooth heatmap canvas source ─────────────────────────
    const heatCanvas = document.createElement('canvas');
    heatCanvas.width  = SMOOTH_COLS;
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
      id:     'heatmap-layer',
      type:   'raster',
      source: 'heatmap',
      layout: { visibility: layersRef.current.heatmap ? 'visible' : 'none' },
      paint:  {
        'raster-opacity':    0.25,
        'raster-resampling': 'linear',
      },
    }, insertBefore);

    map.triggerRepaint();
    diagnoseHeatmap(map);

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
        'fill-color':   '#DDEBE2',
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
      minzoom: 10,
      layout: {
        visibility: layersRef.current.boundaries ? 'visible' : 'none',
        'text-field': ['get', 'wardName'],
        'text-font': ['Inter Regular'],
        'text-size': 13,
        'text-anchor': 'center',
        'text-allow-overlap': true,
        'text-ignore-placement': true,
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
        'circle-radius':       14,
        'circle-color':        ['get', 'color'],
        'circle-stroke-width': 3,
        'circle-stroke-color': '#ffffff',
        'circle-shadow-color': 'rgba(0,0,0,0.35)',
        'circle-shadow-radius': 4,
        'circle-shadow-offset': [0, 2],
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
        'text-font': ['Inter Bold'],
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

    // 7 – Ward hover interactions ─────────────────────────────
    // AQI is computed live at the hovered point via IDW, so it always
    // reflects current station data even if stations loaded after map init.
    let hoveredId = null;
    let hoverTimeout = null;

    // (removed local stationCounts)

    map.on('mousemove', 'wards-hover', e => {
      if (!e.features?.length) return;
      const feat = e.features[0];
      const id   = feat.properties.wardCode;
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

      // Position tooltip offset from cursor, keep inside map edges
      const canvas = map.getCanvas();
      const rect = canvas.getBoundingClientRect();
      const x = e.point.x, y = e.point.y;
      const offsetX = 16, offsetY = 16;

      // Clear any pending remove to prevent flicker
      if (hoverTimeout) { clearTimeout(hoverTimeout); hoverTimeout = null; }

      popupRef.current.setLngLat(e.lngLat).setHTML(`
        <div class="shwas-popup-inner shwas-ward-tooltip">
          <div class="shwas-popup-name">${feat.properties.wardName ?? id} ${id ? `(${id})` : ''}</div>
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

    // Click ward to pin in left panel
    map.on('click', 'wards-hover', e => {
      e.originalEvent.stopPropagation();
      if (!e.features?.length) return;
      const feat = e.features[0];
      const wardObj = {
        id: feat.properties.wardCode,
        name: feat.properties.wardName,
        ward: feat.properties.wardCode,
        aqi: wardAqiRef.current[feat.properties.wardCode]?.aqi ?? null,
        lat: e.lngLat.lat,
        lon: e.lngLat.lng,
        agency: 'BMC',
      };
      onStationClickRef.current?.(wardObj);
      popupRef.current.remove();
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
          <div class="shwas-popup-sub">${p.agency} · Ward ${p.ward}</div>
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
      // Only respond if click is on land
      if (!isLand(lng, lat, allFeatures)) return;
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
        onClickEstimateRef.current?.({ ...data, lat, lon: lng });
      } catch (err) {
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

    // Save original pixels so slider can restore at offset=0
    // (GNN pass is done; this is the best-quality baseline)
    try {
      originalPixelsRef.current = ctx.getImageData(0, 0, COLS, ROWS);
    } catch {}
  };

  // ── Helpers ──────────────────────────────────────────────────
  function buildStationFC(pts) {
    return {
      type: 'FeatureCollection',
      features: (pts ?? []).filter(s => s.aqi != null).map(s => ({
        type: 'Feature',
        properties: { id: s.id, name: s.name, agency: s.agency, ward: s.ward, aqi: s.aqi, color: getAQIColor(s.aqi) },
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
      })),
    };
  }

  /** Return stations with AQI values at the given forecast offset (0 = live). */
  function getStationsAtOffset(stations, fcMap, offset) {
    if (!offset || !fcMap) return stations;
    return stations.map(s => {
      const fc  = fcMap[s.id];
      const idx = Math.min(offset, (fc?.length ?? 0) - 1);
      const aqi = (idx >= 0 ? fc[idx]?.aqi : null) ?? s.aqi;
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
    const vis = (id, on) => { try { map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'); } catch {} };
    vis('stations-circle',   layers.stations);
    vis('stations-ring',     layers.stations);
    vis('stations-labels',   layers.stations);
    vis('wards-line',        layers.boundaries);
    vis('wards-hover',       layers.boundaries);
    vis('wards-hover-outline', layers.boundaries);
    vis('wards-labels',      layers.boundaries);
    vis('wards-pop',         layers.population);
    vis('slums-fill',        layers.slums);
    vis('heatmap-layer',     layers.heatmap);
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
      try { map.setFilter('stations-circle', filter); } catch {}
      try { map.setFilter('stations-labels', filter); } catch {}
    }
  }, [stationPoints]);

  // ── Redraw heatmap when live station data arrives ────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    // Only redraw if we have actual AQI data (not the initial static seed)
    const hasRealData = (stationPoints ?? []).some(s => s.aqi != null);
    if (hasRealData) {
      const wardsSource = map.getSource('wards');
      const b = [[GEO.W, GEO.S], [GEO.E, GEO.N]];
      drawHeatmap(map, stationPoints ?? [], wardsSource?.getData() ?? { type: 'FeatureCollection', features: [] }, b);
      diagnoseHeatmap(map);
    }
  }, [stationPoints]);

  // ── Update ward AQI choropleth when station data changes ──────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    
    const colorStops = Object.entries(wardAqi).flatMap(([code, data]) => [code, getAQIColor(data.aqi)]);
    if (colorStops.length) {
      try {
        map.setPaintProperty('wards-aqi', 'fill-color', [
          'match', ['get', 'wardCode'], ...colorStops, '#CCCCCC'
        ]);
      } catch {}
    } else {
      try {
        map.setPaintProperty('wards-aqi', 'fill-color', '#CCCCCC');
      } catch {}
    }
  }, [wardAqi]);

  // ── Selected station highlight ───────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !styleReadyRef.current) return;
    try { map.setFilter('stations-ring', ['==', ['get', 'id'], selectedStation?.id || '']); } catch {}
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
      const offset   = forecastOffset ?? 0;
      const fcMap    = allForecastsRef.current;
      const stations = stationPointsRef.current ?? [];
      const adjusted = getStationsAtOffset(stations, fcMap, offset);

      // 1. Recolour station circles
      const src = map.getSource('stations');
      if (src) src.setData(buildStationFC(adjusted));

      // 2. Recolour heatmap canvas (smooth surface, clipped to wards)
      const wardsSource = map.getSource('wards');
      const b = [[GEO.W, GEO.S], [GEO.E, GEO.N]];
      
      const currentWardGeoJSON = wardsSource?.getData() ?? { type: 'FeatureCollection', features: [] };
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
          } catch {}
        } else {
          try {
            map.setPaintProperty('wards-aqi', 'fill-color', '#CCCCCC');
          } catch {}
        }
      }
    });

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [forecastOffset, allForecasts]); // eslint-disable-line react-hooks/exhaustive-deps

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

  // ── Fire markers ────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    // Always remove old fire markers first
    fireMarkersRef.current.forEach(m => m.remove());
    fireMarkersRef.current = [];

    if (!map || !styleReadyRef.current || !firesData?.length || !layers.windFires) return;

    firesData.forEach(fire => {
      if (fire.lat == null || fire.lon == null) return;
      const el = document.createElement('div');
      el.className = 'fire-marker';
      el.setAttribute('aria-label', `Fire ${fire.distance_km ?? '?'} km away`);
      const mw = fire.intensity_mw != null ? `${fire.intensity_mw}MW` : '';
      const km = fire.distance_km  != null ? `${fire.distance_km}km` : '';
      el.innerHTML = `
        <div class="fire-marker__triangle"></div>
        <div class="fire-marker__label">${[km, mw].filter(Boolean).join(' · ')}</div>
      `;
      const marker = new maplibregl.Marker({ element: el, anchor: 'bottom' })
        .setLngLat([fire.lon, fire.lat])
        .addTo(map);
      fireMarkersRef.current.push(marker);
    });
  }, [firesData, layers.windFires]);

  return (
    <div className="shwas-map-wrap">
      <div ref={containerRef} className="shwas-map-canvas" />

      {heatLoading && layers.heatmap && (
        <div className="heat-progress" role="status" aria-live="polite">
          Building surface model...
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
