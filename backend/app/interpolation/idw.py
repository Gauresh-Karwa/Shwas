import math
from dataclasses import dataclass

def haversine_km(lat1,lon1,lat2,lon2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2-lon1)
    a = math.sin(dphi/2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

@dataclass
class InterpolationResult:
    estimated_aqi : float
    nearest_station_distance_km: float
    confidence: str
    stations_used: int

def _confidence_for_distance(distance_km: float) -> str:
    if distance_km <= 2:
        return "high"
    elif distance_km <= 5:
        return "medium"
    elif distance_km <= 10:
        return "low"
    else:
        return "insufficient"

def idw_interpolate(target_lat: float, target_lon: float, station_points:list[tuple[float,float,float]], power : float = 2) -> InterpolationResult | None:
    if not station_points:
        return None

    distances = [haversine_km(target_lat,target_lon,lat,lon) for lat,lon,_ in station_points]
    nearest_distance = min(distances)

    if nearest_distance < 0.01:
        idx = distances.index(nearest_distance)
        return InterpolationResult(
            estimated_aqi=station_points[idx][2],
            nearest_station_distance_km=nearest_distance,
            confidence="high",
            stations_used=1,
        )

    weights = [1 / (d ** power) for d in distances]
    weighted_sum = sum(w * point[2] for w , point in zip(weights,station_points))
    total_weight = sum(weights)
    estimate = weighted_sum / total_weight

    return InterpolationResult(
        estimated_aqi=round(estimate, 1),
        nearest_station_distance_km=round(nearest_distance, 2),
        confidence=_confidence_for_distance(nearest_distance),
        stations_used=len(station_points),
    )
    