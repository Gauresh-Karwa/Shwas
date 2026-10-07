"""
Air-mass back-trajectory.

Traces the air that is arriving at a location backwards in time, one hour at
a time, using the hourly 10 m wind at that location. That turns "the wind is
from the west right now" into "this air was over X six hours ago and passed
near Y on the way", which is a much stronger statement for source attribution.

Method: the wind direction is meteorological (the direction the wind blows
FROM), so each hour the parcel is moved a distance of speed x 3600 s along that
bearing, i.e. back towards where the air came from.

Known simplifications (stated on purpose, not hidden):
  * the wind at the arrival point is used for the whole path (no wind field),
  * 10 m wind understates transport in the boundary layer,
  * no vertical mixing or deposition.
They are acceptable for a 6 to 12 hour, tens-of-kilometres path over Mumbai,
and the corridor used for matching sources is deliberately wide.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from app.analytics.geo import point_in_geometry
from app.attribution.weather_client import compass_direction
from app.interpolation.idw import bearing_deg, haversine_km

DEFAULT_HOURS = 6
MAX_HOURS = 24
CALM_MPS = 0.5            # below this the parcel is treated as not moving
STAGNANT_MEAN_MPS = 1.5   # same calm threshold as the rest of the attribution code
CORRIDOR_KM = 5.0         # a source this close to the path can have fed the air
MIN_UPWIND_HOURS = 0.5    # closer than this to arrival counts as "at the station"
DENSIFY_STEP_KM = 1.0     # spacing used to test which wards / sea the path crosses
COAST_BAND_DEG = 0.03     # latitude band used to find the city's western edge
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class WindHour:
    """Wind at the arrival point `hours_back` hours before arrival (0 = latest hour)."""
    hours_back: int
    speed_mps: float | None
    direction_deg: float | None  # meteorological: direction the wind blows FROM


@dataclass(frozen=True)
class TrajectoryPoint:
    hours_back: float
    lat: float
    lon: float


@dataclass(frozen=True)
class WardShape:
    ward_id: str
    ward_name: str
    geometry: dict


@dataclass
class FireOnPath:
    lat: float
    lon: float
    frp_mw: float
    distance_to_path_km: float
    hours_upwind: float


@dataclass
class AirMassTrajectory:
    hours: int
    points: list[TrajectoryPoint]
    mean_speed_mps: float
    path_km: float
    stagnant: bool
    arrival_direction_deg: float | None      # wind direction at arrival (FROM)
    origin_distance_km: float
    origin_bearing_deg: float | None
    wards_crossed: list[dict] = field(default_factory=list)   # oldest first
    marine_hours: float | None = None        # lower bound; None = could not be determined
    fires_on_path: list[FireOnPath] = field(default_factory=list)
    fires_off_path: int = 0

    # ── presentation helpers ──────────────────────────────────────────────

    @property
    def origin_compass(self) -> str | None:
        return None if self.origin_bearing_deg is None else compass_direction(self.origin_bearing_deg)

    @property
    def over_sea(self) -> bool:
        return bool(self.marine_hours and self.marine_hours >= 1.0)

    def summary(self) -> str:
        """One or two plain sentences, deterministic (used as the no-LLM fallback)."""
        if self.stagnant:
            text = (f"Winds were light over the last {self.hours} h (about {self.mean_speed_mps:.1f} m/s), "
                    f"so pollutants are not being dispersed quickly.")
        else:
            text = (f"Over the last {self.hours} h the air travelled about {self.path_km:.0f} km "
                    f"to get here, arriving from the {self.origin_compass}.")
            if self.over_sea:
                text += f" At least {self.marine_hours:.0f} h of that was over the sea to the west."
            elif self.wards_crossed:
                names = ", ".join(w["ward_name"] for w in self.wards_crossed[-3:])
                text += f" It passed over {names}."
        if self.fires_on_path:
            f = min(self.fires_on_path, key=lambda x: x.distance_to_path_km)
            where = "right on that path" if f.distance_to_path_km < 1 else f"about {f.distance_to_path_km:.0f} km from that path"
            text += f" A fire detection lies {where}, roughly {f.hours_upwind:.0f} h upwind."
        elif self.fires_off_path:
            text += " Nearby fire detections are not on the air's path."
        return text

    def to_dict(self) -> dict:
        return {
            "hours": self.hours,
            "path_km": round(self.path_km, 1),
            "mean_speed_mps": round(self.mean_speed_mps, 1),
            "stagnant": self.stagnant,
            "arrival_from": {
                "direction_deg": self.arrival_direction_deg,
                "compass": None if self.arrival_direction_deg is None else compass_direction(self.arrival_direction_deg),
            },
            "origin": {
                "lat": round(self.points[-1].lat, 4),
                "lon": round(self.points[-1].lon, 4),
                "distance_km": round(self.origin_distance_km, 1),
                "bearing_deg": None if self.origin_bearing_deg is None else round(self.origin_bearing_deg),
                "compass": self.origin_compass,
                "hours_back": self.points[-1].hours_back,
            },
            "points": [{"hours_back": p.hours_back, "lat": round(p.lat, 4), "lon": round(p.lon, 4)} for p in self.points],
            "over": {
                "wards": self.wards_crossed,
                "marine_hours": None if self.marine_hours is None else round(self.marine_hours, 1),
                "sea": self.over_sea,
            },
            "fires_on_path": [
                {"lat": f.lat, "lon": f.lon, "frp_mw": f.frp_mw,
                 "distance_to_path_km": round(f.distance_to_path_km, 1),
                 "hours_upwind": round(f.hours_upwind, 1)}
                for f in self.fires_on_path
            ],
            "fires_off_path": self.fires_off_path,
            "summary": self.summary(),
        }


# ── geometry ──────────────────────────────────────────────────────────────

def destination_point(lat: float, lon: float, bearing: float, distance_km: float) -> tuple[float, float]:
    """Point reached by travelling `distance_km` from (lat, lon) along `bearing` (degrees)."""
    delta = distance_km / EARTH_RADIUS_KM
    theta = math.radians(bearing)
    phi1, lam1 = math.radians(lat), math.radians(lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta))
    lam2 = lam1 + math.atan2(math.sin(theta) * math.sin(delta) * math.cos(phi1),
                             math.cos(delta) - math.sin(phi1) * math.sin(phi2))
    return math.degrees(phi2), (math.degrees(lam2) + 540) % 360 - 180


def back_trajectory(lat: float, lon: float, winds: Sequence[WindHour]) -> list[TrajectoryPoint]:
    """Trace the parcel arriving at (lat, lon) backwards, one step per wind hour.

    `winds` are ordered by `hours_back` (0 first). Step k moves the parcel back
    along the wind that blew during that hour. Missing or calm wind leaves the
    parcel where it is for that hour.
    """
    points = [TrajectoryPoint(0.0, lat, lon)]
    cur_lat, cur_lon = lat, lon
    for w in sorted(winds, key=lambda x: x.hours_back):
        if w.speed_mps is not None and w.direction_deg is not None and w.speed_mps >= CALM_MPS:
            cur_lat, cur_lon = destination_point(cur_lat, cur_lon, w.direction_deg, w.speed_mps * 3.6)
        points.append(TrajectoryPoint(float(w.hours_back + 1), cur_lat, cur_lon))
    return points


def _to_xy_km(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    kx = math.cos(math.radians(lat0)) * math.pi / 180 * EARTH_RADIUS_KM
    ky = math.pi / 180 * EARTH_RADIUS_KM
    return lon * kx, lat * ky


def distance_to_path(lat: float, lon: float, points: Sequence[TrajectoryPoint]) -> tuple[float, float]:
    """(shortest distance in km, hours_back at that closest point) from a location to the path."""
    if len(points) == 1:
        return haversine_km(lat, lon, points[0].lat, points[0].lon), points[0].hours_back
    px, py = _to_xy_km(lat, lon, lat)
    best = (float("inf"), 0.0)
    for a, b in zip(points, points[1:]):
        ax, ay = _to_xy_km(a.lat, a.lon, lat)
        bx, by = _to_xy_km(b.lat, b.lon, lat)
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best[0]:
            best = (d, a.hours_back + t * (b.hours_back - a.hours_back))
    return best


def _densify(points: Sequence[TrajectoryPoint], step_km: float = DENSIFY_STEP_KM) -> list[tuple[float, float, float, float]]:
    """Samples along the path as (lat, lon, hours_back, dt_hours), about `step_km` apart."""
    dense = []
    for a, b in zip(points, points[1:]):
        seg_km = haversine_km(a.lat, a.lon, b.lat, b.lon)
        n = max(1, math.ceil(seg_km / step_km))
        dt = (b.hours_back - a.hours_back) / n
        for i in range(n):
            f = (i + 0.5) / n
            dense.append((a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon),
                          a.hours_back + f * (b.hours_back - a.hours_back), dt))
    return dense


# ── what the path crossed ─────────────────────────────────────────────────

def _ward_vertices(wards: Iterable[WardShape]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for w in wards:
        g = w.geometry
        polys = [g["coordinates"]] if g.get("type") == "Polygon" else g.get("coordinates", [])
        for poly in polys:
            for lon, lat, *_ in poly[0]:
                pts.append((lat, lon))
    return pts


def _is_west_of_coast(lat: float, lon: float, vertices: list[tuple[float, float]]) -> bool | None:
    """True if the point lies west of the city's western edge at its latitude.

    Mumbai is a west-coast peninsula, so a point outside every ward and west
    of the westernmost ward vertex in the same latitude band is over the
    Arabian Sea. Returns None when no ward lies in that band (cannot tell),
    which is why the sea time reported is a lower bound: stretches south of
    Colaba or north of Dahisar are not counted.
    """
    band = [v_lon for v_lat, v_lon in vertices if abs(v_lat - lat) <= COAST_BAND_DEG]
    if not band:
        return None
    return lon < min(band)


def analyse_path(points: Sequence[TrajectoryPoint], wards: Sequence[WardShape]) -> tuple[list[dict], float | None]:
    """(wards crossed oldest first, hours spent over the sea or None if unknown)."""
    if not wards:
        return [], None
    vertices = _ward_vertices(wards)
    crossed: dict[str, dict] = {}
    marine = 0.0
    determinable = False
    for lat, lon, hb, dt in _densify(points):
        hit = next((w for w in wards if point_in_geometry(lat, lon, w.geometry)), None)
        if hit is not None:
            determinable = True
            crossed.setdefault(hit.ward_id, {"ward_id": hit.ward_id, "ward_name": hit.ward_name,
                                             "hours_back": round(hb, 1), "_t": hb})
            crossed[hit.ward_id]["_t"] = max(crossed[hit.ward_id]["_t"], hb)
            continue
        west = _is_west_of_coast(lat, lon, vertices)
        if west is not None:
            determinable = True
            if west:
                marine += dt
    ordered = sorted(crossed.values(), key=lambda w: -w["_t"])   # oldest first
    for w in ordered:
        w["hours_back"] = round(w.pop("_t"), 1)
    return ordered, (marine if determinable else None)


def classify_fires(points: Sequence[TrajectoryPoint], fires: Sequence,
                   corridor_km: float = CORRIDOR_KM) -> tuple[list[FireOnPath], int]:
    """Split fire detections into those the air passed near (upwind) and the rest.

    A fire is on the path when it is within `corridor_km` of it and the air
    passed it at least MIN_UPWIND_HOURS before arriving. Detections that are
    only near the arrival point itself are not treated as upwind sources.
    Each fire needs latitude, longitude and frp_mw attributes.
    """
    on_path: list[FireOnPath] = []
    for f in fires:
        d, hb = distance_to_path(f.latitude, f.longitude, points)
        if d <= corridor_km and hb >= MIN_UPWIND_HOURS:
            on_path.append(FireOnPath(f.latitude, f.longitude, f.frp_mw, d, hb))
    on_path.sort(key=lambda x: x.distance_to_path_km)
    return on_path, len(fires) - len(on_path)


# ── entry point ───────────────────────────────────────────────────────────

def build_trajectory(lat: float, lon: float, winds: Sequence[WindHour], fires: Sequence = (),
                     wards: Sequence[WardShape] = ()) -> AirMassTrajectory | None:
    """Full analysis for one location. Returns None when there is no wind data."""
    usable = [w for w in winds if w.speed_mps is not None]
    if not usable:
        return None
    points = back_trajectory(lat, lon, winds)
    speeds = [w.speed_mps for w in usable]
    mean_speed = sum(speeds) / len(speeds)
    path_km = sum(haversine_km(a.lat, a.lon, b.lat, b.lon) for a, b in zip(points, points[1:]))
    origin = points[-1]
    origin_km = haversine_km(lat, lon, origin.lat, origin.lon)
    latest = min(usable, key=lambda w: w.hours_back)
    stagnant = mean_speed < STAGNANT_MEAN_MPS
    wards_crossed, marine_hours = analyse_path(points, wards)
    on_path, off_path = classify_fires(points, fires)
    return AirMassTrajectory(
        hours=len(winds),
        points=points,
        mean_speed_mps=mean_speed,
        path_km=path_km,
        stagnant=stagnant,
        arrival_direction_deg=latest.direction_deg,
        origin_distance_km=origin_km,
        origin_bearing_deg=bearing_deg(lat, lon, origin.lat, origin.lon) if origin_km > 0.05 else None,
        wards_crossed=wards_crossed,
        marine_hours=marine_hours,
        fires_on_path=on_path,
        fires_off_path=off_path,
    )
