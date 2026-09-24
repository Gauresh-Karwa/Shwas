import math
from dataclasses import dataclass
CALM_THRESHOLD_MPS = 1.5

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = (math.radians(lat1), math.radians(lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def bearing_deg(from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> float:
    lat1 = math.radians(from_lat)
    lat2 = math.radians(to_lat)
    dlon = math.radians(to_lon - from_lon)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360

def _wind_factor(target_lat: float, target_lon: float, station_lat: float, station_lon: float, wind_from_deg: float, wind_speed_mps: float, alpha: float) -> float:
    alpha_eff = alpha * min(wind_speed_mps / CALM_THRESHOLD_MPS, 1.0)
    if alpha_eff < 1e-06:
        return 1.0
    brg = bearing_deg(target_lat, target_lon, station_lat, station_lon)
    theta = math.radians(brg - wind_from_deg)
    factor = 1.0 + alpha_eff * math.cos(theta)
    return max(0.05, factor)

@dataclass
class InterpolationResult:
    estimated_aqi: float
    nearest_station_distance_km: float
    confidence: str
    stations_used: int
    wind_corrected: bool = False

def _confidence_for_distance(distance_km: float) -> str:
    if distance_km <= 2:
        return 'high'
    elif distance_km <= 5:
        return 'medium'
    elif distance_km <= 10:
        return 'low'
    else:
        return 'insufficient'

def idw_interpolate(target_lat: float, target_lon: float, station_points: list[tuple[float, float, float]], power: float=2, wind_speed_mps: float | None=None, wind_from_deg: float | None=None, wind_alpha: float=0.6) -> InterpolationResult | None:
    if not station_points:
        return None
    use_wind = wind_speed_mps is not None and wind_from_deg is not None and (wind_speed_mps >= CALM_THRESHOLD_MPS)
    distances = [haversine_km(target_lat, target_lon, lat, lon) for lat, lon, _ in station_points]
    nearest_distance = min(distances)
    if nearest_distance < 0.01:
        idx = distances.index(nearest_distance)
        return InterpolationResult(estimated_aqi=station_points[idx][2], nearest_station_distance_km=nearest_distance, confidence='high', stations_used=1, wind_corrected=False)
    weights = []
    for (lat, lon, _), dist in zip(station_points, distances):
        w = 1.0 / dist ** power
        if use_wind:
            w *= _wind_factor(target_lat, target_lon, lat, lon, wind_from_deg, wind_speed_mps, wind_alpha)
        weights.append(w)
    weighted_sum = sum((w * point[2] for w, point in zip(weights, station_points)))
    total_weight = sum(weights)
    estimate = weighted_sum / total_weight
    return InterpolationResult(estimated_aqi=round(estimate, 1), nearest_station_distance_km=round(nearest_distance, 2), confidence=_confidence_for_distance(nearest_distance), stations_used=len(station_points), wind_corrected=use_wind)
