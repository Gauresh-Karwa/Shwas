// MapLibre layer management for the air-mass back-trajectory.
import { airMassFeatureCollection } from './airMass';

const SOURCE_ID = 'air-mass';
const PATH_LAYER = 'air-mass-path';
const CASING_LAYER = 'air-mass-casing';
const POINTS_LAYER = 'air-mass-points';

export function addAirMassLayers(map, beforeLayerId) {
  if (map.getSource(SOURCE_ID)) return;

  map.addSource(SOURCE_ID, {
    type: 'geojson',
    data: { type: 'FeatureCollection', features: [] },
  });

  // White casing for contrast against varied backgrounds
  map.addLayer(
    {
      id: CASING_LAYER,
      type: 'line',
      source: SOURCE_ID,
      filter: ['==', ['get', 'kind'], 'path'],
      paint: {
        'line-color': '#FFFFFF',
        'line-width': 4.5,
        'line-opacity': 0.8,
      },
    },
    beforeLayerId,
  );

  // Core trajectory path
  map.addLayer(
    {
      id: PATH_LAYER,
      type: 'line',
      source: SOURCE_ID,
      filter: ['==', ['get', 'kind'], 'path'],
      paint: {
        'line-color': '#1D5C8C',
        'line-width': 2.5,
        'line-opacity': 0.95,
        'line-dasharray': [2, 1.5],
      },
    },
    beforeLayerId,
  );

  // Hourly markers along the trajectory
  map.addLayer(
    {
      id: POINTS_LAYER,
      type: 'circle',
      source: SOURCE_ID,
      filter: ['==', ['get', 'kind'], 'hour'],
      paint: {
        'circle-color': ['case', ['get', 'origin'], '#1D5C8C', '#FFFFFF'],
        'circle-stroke-color': '#1D5C8C',
        'circle-stroke-width': 2,
        'circle-radius': ['case', ['get', 'origin'], 5, 3.5],
      },
    },
    beforeLayerId,
  );
}

export function setAirMass(map, airMass, visible = true) {
  const source = map.getSource(SOURCE_ID);
  if (!source) return false;

  const data = visible && airMass ? airMassFeatureCollection(airMass) : { type: 'FeatureCollection', features: [] };
  source.setData(data);
  return Boolean(data.features && data.features.length > 0);
}
