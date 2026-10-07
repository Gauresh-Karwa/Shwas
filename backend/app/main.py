from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from app.routers.interpolate import router as interpolate_router
from app.routers.forecast import router as forecast_router
from app.attribution.weather_client import get_wind_data
from app.attribution.fire_client import get_nearby_fires
from app.attribution.news_search import search_air_quality_news
from app.attribution.llm_explainer import get_explanation
from app.config import settings
from app.routers.wards import router as wards_router
from app.routers.attribution import router as attribution_router
from app.routers.recommendations import router as recommendations_router
from app.routers.waste import router as waste_router

app = FastAPI(
    title="Shwas AQI API",
    description="Real-time AQI interpolation and forecasting for Mumbai.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(interpolate_router)
app.include_router(forecast_router)
app.include_router(wards_router)
app.include_router(attribution_router)
app.include_router(recommendations_router)
app.include_router(waste_router)

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/api/attribution", tags=["attribution"])
def attribution(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    station_name: str = Query("Mumbai", description="Station or area name for news search"),
    aqi: float = Query(100.0),
    category: str = Query("Moderate"),
    dominant_pollutant: str = Query("PM2.5"),
):
    wind = None
    fires = []
    news = []
    explanation = f"Air quality is {category} (AQI {int(aqi)}), primarily driven by {dominant_pollutant}."

    try:
        wind = get_wind_data(lat, lon, settings.OPENWEATHERMAP_API_KEY)
    except Exception:
        pass

    try:
        fires = get_nearby_fires(settings.FIRMS_MAP_KEY, lat, lon)
    except Exception:
        pass

    try:
        news = search_air_quality_news(area_name=station_name)
    except Exception:
        pass

    try:
        explanation = get_explanation(
            station_name=station_name,
            aqi_value=int(aqi),
            category=category,
            dominant_pollutant=dominant_pollutant,
            wind=wind,
            fires=fires,
            news=news,
            api_key=settings.GEMINI_API_KEY,
        )
    except Exception:
        pass

    return {
        "wind": {
            "speed_mps": wind.speed_mps if wind else None,
            "direction_deg": wind.direction_deg if wind else None,
            "compass": wind.description if wind else None,
        } if wind else None,
        "fires": [
            {
                "lat": f.latitude,
                "lon": f.longitude,
                "distance_km": round(f.distance_km, 1),
                "frp_mw": f.frp_mw,
            }
            for f in fires[:5]
        ],
        "news": [
            {"title": n.title, "url": n.url, "domain": n.domain}
            for n in news[:3]
        ],
        "explanation": explanation,
    }
