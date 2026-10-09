// MapLibre air-mass back-trajectory renderer.
//
// Draws N_LANES straight parallel lines with a filled arrowhead at the
// station end, showing the direction the air arrived from.
// No animation — purely static.

import { airMassFeatureCollection } from './airMass';

const SOURCE_ID = 'air-mass';
const CANVAS_ID = 'air-mass-arrow-canvas';

// ── Visual config ─────────────────────────────────────────────────────────────
const N_LANES       = 4;     // parallel lines
const CORRIDOR_PX   = 30;    // half-width of the band (px each side of path centre)
const LINE_WIDTH    = 1.4;   // thin
const ARROW_SIZE    = 10;    // arrowhead length (px)
const ARROW_ANGLE   = 22;    // arrowhead opening (degrees)
const COLOR         = 'rgba(30, 160, 220, ';  // sky-blue

// ── Module state ──────────────────────────────────────────────────────────────
let _map     = null;
let _airMass = null;
let _visible = false;
let _canvas  = null;
let _ctx     = null;
let _ro      = null;

// ── Public API ────────────────────────────────────────────────────────────────

export function addAirMassLayers(map, _beforeLayerId) {
  _map = map;
  if (!map.getSource(SOURCE_ID)) {
    map.addSource(SOURCE_ID, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });
  }
  _ensureCanvas();
}

export function setAirMass(map, airMass, visible = true) {
  _map     = map;
  _airMass = airMass;
  _visible = visible;

  const source = map.getSource(SOURCE_ID);
  if (source) {
    const data = visible && airMass
      ? airMassFeatureCollection(airMass)
      : { type: 'FeatureCollection', features: [] };
    source.setData(data);
  }

  _ensureCanvas();

  if (visible && airMass && _getPoints().length >= 2) {
    _draw();
    return true;
  }
  _clear();
  return false;
}

// ── Canvas bootstrap ──────────────────────────────────────────────────────────

function _ensureCanvas() {
  if (!_map) return;
  const container = _map.getContainer();
  if (container.querySelector(`#${CANVAS_ID}`)) return;

  _canvas    = document.createElement('canvas');
  _canvas.id = CANVAS_ID;
  Object.assign(_canvas.style, {
    position:      'absolute',
    inset:         '0',
    width:         '100%',
    height:        '100%',
    pointerEvents: 'none',
    zIndex:        '2',
  });
  container.appendChild(_canvas);
  _ctx = _canvas.getContext('2d');

  _sizeCanvas();
  _ro = new ResizeObserver(() => { _sizeCanvas(); _draw(); });
  _ro.observe(container);

  _map.on('move',   _draw);
  _map.on('zoom',   _draw);
  _map.on('rotate', _draw);
  _map.on('pitch',  _draw);
}

function _sizeCanvas() {
  if (!_canvas || !_map) return;
  const c   = _map.getContainer();
  const dpr = window.devicePixelRatio || 1;
  _ctx.setTransform(1, 0, 0, 1, 0, 0);
  _canvas.width  = c.clientWidth  * dpr;
  _canvas.height = c.clientHeight * dpr;
  _ctx.scale(dpr, dpr);
}

function _clear() {
  if (!_ctx || !_canvas) return;
  const dpr = window.devicePixelRatio || 1;
  _ctx.clearRect(0, 0, _canvas.width / dpr, _canvas.height / dpr);
}

// ── Drawing ───────────────────────────────────────────────────────────────────

function _getPoints() {
  if (!_airMass?.points) return [];
  // oldest first → direction of travel is origin → station
  return [..._airMass.points].sort((a, b) => b.hours_back - a.hours_back);
}

function _draw() {
  if (!_ctx || !_canvas || !_visible || !_airMass) return;
  _clear();

  const pts = _getPoints();
  if (pts.length < 2) return;

  // Project all geo points to pixel space
  const px = pts.map(p => {
    const { x, y } = _map.project([p.lon, p.lat]);
    return { x, y };
  });

  // Overall direction vector (from oldest point → station = last point)
  // Use first and last projected pixel for a stable, straight direction.
  const first = px[0];
  const last  = px[px.length - 1];
  const dx    = last.x - first.x;
  const dy    = last.y - first.y;
  const mag   = Math.sqrt(dx * dx + dy * dy) || 1;

  // Unit tangent (flow direction) and normal (perpendicular, for lane offset)
  const tx = dx / mag;  // unit tangent x
  const ty = dy / mag;  // unit tangent y
  const nx = -ty;       // unit normal x
  const ny =  tx;       // unit normal y

  const angleRad = (ARROW_ANGLE * Math.PI) / 180;

  for (let lane = 0; lane < N_LANES; lane++) {
    // Spread lanes evenly: −1 … +1 mapped to −CORRIDOR_PX … +CORRIDOR_PX
    const laneT    = N_LANES === 1 ? 0 : (lane / (N_LANES - 1)) * 2 - 1;
    const offset   = laneT * CORRIDOR_PX;
    const alpha    = 0.72 - Math.abs(laneT) * 0.20;  // edges slightly lighter

    // Lane start = first pixel + lateral offset
    const sx = first.x + nx * offset;
    const sy = first.y + ny * offset;
    // Lane end   = last  pixel + lateral offset
    const ex = last.x  + nx * offset;
    const ey = last.y  + ny * offset;

    // ── Straight line ──────────────────────────────────────────────────────
    _ctx.beginPath();
    _ctx.moveTo(sx, sy);
    _ctx.lineTo(ex, ey);
    _ctx.strokeStyle = COLOR + alpha.toFixed(2) + ')';
    _ctx.lineWidth   = LINE_WIDTH;
    _ctx.lineCap     = 'round';
    _ctx.stroke();

    // ── Filled arrowhead at the station end ───────────────────────────────
    const angle = Math.atan2(ty, tx);
    const l1x   = ex - ARROW_SIZE * Math.cos(angle - angleRad);
    const l1y   = ey - ARROW_SIZE * Math.sin(angle - angleRad);
    const l2x   = ex - ARROW_SIZE * Math.cos(angle + angleRad);
    const l2y   = ey - ARROW_SIZE * Math.sin(angle + angleRad);

    _ctx.beginPath();
    _ctx.moveTo(ex, ey);
    _ctx.lineTo(l1x, l1y);
    _ctx.lineTo(l2x, l2y);
    _ctx.closePath();
    _ctx.fillStyle = COLOR + alpha.toFixed(2) + ')';
    _ctx.fill();
  }
}
