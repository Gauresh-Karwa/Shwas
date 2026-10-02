from __future__ import annotations


def _ring_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    pts = ring if ring[0] == ring[-1] else ring + [ring[0]]
    area_acc = 0.0
    cx_acc = 0.0
    cy_acc = 0.0
    for i in range(len(pts) - 1):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[i + 1][0], pts[i + 1][1]
        cross = x0 * y1 - x1 * y0
        area_acc += cross
        cx_acc += (x0 + x1) * cross
        cy_acc += (y0 + y1) * cross
    signed_area = area_acc / 2.0

    if abs(signed_area) < 1e-12:
        unique_pts = pts[:-1] if len(pts) > 1 else pts
        n = len(unique_pts) or 1
        avg_lon = sum(p[0] for p in unique_pts) / n
        avg_lat = sum(p[1] for p in unique_pts) / n
        return avg_lon, avg_lat, 0.0

    cx = cx_acc / (6.0 * signed_area)
    cy = cy_acc / (6.0 * signed_area)
    return cx, cy, signed_area


def polygon_centroid(geometry: dict) -> tuple[float, float]:
    gtype = geometry.get("type")
    coords = geometry["coordinates"]

    if gtype == "Polygon":
        exterior = coords[0]
        lon, lat, _ = _ring_centroid(exterior)
        return lat, lon

    if gtype == "MultiPolygon":
        best = None
        for polygon in coords:
            exterior = polygon[0]
            lon, lat, area = _ring_centroid(exterior)
            if best is None or abs(area) > abs(best[2]):
                best = (lon, lat, area)
        lon, lat, _ = best
        return lat, lon

    raise ValueError(f"Unsupported geometry type for centroid: {gtype!r}")


def _point_in_ring(lat: float, lon: float, ring: list[list[float]]) -> bool:
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_geometry(lat: float, lon: float, geometry: dict) -> bool:
    gtype = geometry.get("type")
    coords = geometry["coordinates"]

    if gtype == "Polygon":
        return _point_in_ring(lat, lon, coords[0])

    if gtype == "MultiPolygon":
        return any(_point_in_ring(lat, lon, polygon[0]) for polygon in coords)

    raise ValueError(f"Unsupported geometry type for point containment: {gtype!r}")