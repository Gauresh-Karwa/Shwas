from dataclasses import dataclass
from datetime import datetime, timezone

import requests

BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

@dataclass
class WindData:
    speed_mps: float
    direction_deg: float | None 
    description: str
    observed_at: datetime

def get_wind_data(lat: float, lon: float, api_key:str)-> WindData | None:
    params = {"lat": lat, "lon": lon, "appid": api_key, "units": "metric"}

    try: 
        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"OpenWeatherMap request failed: {type(e).__name__}: {e}")
        return None

    wind = data.get("wind", {})
    weather_list = data.get("weather", [])
    description = weather_list[0]["description"] if weather_list else "unknown"

    return WindData(
        speed_mps=wind.get("speed", 0.0),
        direction_deg=wind.get("deg"), 
        description=description,
        observed_at=datetime.fromtimestamp(data["dt"], tz=timezone.utc),
    )

def compass_direction(degrees: float | None) -> str:
    if degrees is None:
        return "variable/calm"
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = round(degrees / 22.5) % 16
    return directions[index]