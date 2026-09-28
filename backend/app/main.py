from fastapi import FastAPI
from app.routers.interpolate import router as interpolate_router
from app.routers.forecast import router as forecast_router

app = FastAPI(
    title="Shwas AQI API",
    description="Real-time AQI interpolation and forecasting for Mumbai.",
    version="1.0.0",
)

app.include_router(interpolate_router)
app.include_router(forecast_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
