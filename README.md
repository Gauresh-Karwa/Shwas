# Shwas (श्वास)

Shwas is a spatio-temporal air quality intelligence engine built for Indian metropolitan regions, deployed and evaluated on the Mumbai municipal sensor grid.

Government monitoring networks face three structural challenges:
1. Spatial sparsity: CPCB monitoring stations are separated by several kilometers. Unmonitored neighborhoods have no direct sensor coverage.
2. Temporal latency: Conventional autoregressive models either fail to capture diurnal traffic spikes or require heavy multi-hour retraining cycles.
3. Lack of actionable context: Pure particulate numbers (e.g. "PM2.5: 142 µg/m³") give citizens and policymakers no indication of origin, whether from local traffic, biomass fires, or coastal wind stalls.

Shwas solves these challenges by combining Graph Attention Networks for continuous spatial interpolation, rolling seasonal autoregression for temporal forecasting, and multi-modal satellite and weather telemetry for causal attribution.

---

## System Architecture

```
[ Ingestion & Data Sanitization ]
   ├── CPCB real-time API (data.gov.in) with exponential backoff retry
   ├── Historical multi-year dataset (Kaggle / CPCB archives)
   └── Physics-based anomaly cleaner (spread ratios, negative rejection)
          │
          ▼
[ Spatial Modeling Engine ] ──────────────► [ Temporal Forecasting Engine ]
   ├── Spatial GNN (Graph Attention Network)     ├── Seasonal ARIMA (1, 0, 1)(1, 0, 0)24
   ├── Distance-biased k-NN topology             ├── Rolling 14-day adaptive window
   └── 22.7% error reduction over IDW            └── 6 / 6 Mumbai station wins over baseline
          │                                              │
          └──────────────────────┬───────────────────────┘
                                 ▼
              [ Chained Spatio-Temporal Predictor ]
                 ├── Forecasts all stations 24h ahead via SARIMA
                 ├── Projects forward station tensors into Spatial GNN
                 ├── Delivers 24h forecast for any (lat, lon) coordinate
                 └── 73% to 81% error reduction over IDW chaining
                                 │
                                 ▼
                 [ Uncertainty Quantification ]
                    ├── SARIMA analytical 95% confidence intervals
                    └── GNN Monte Carlo dropout epistemic variance
                                 │
                                 ▼
                 [ Multi-Modal Attribution Engine ]
                    ├── OpenWeatherMap (wind vectors, dispersion)
                    ├── NASA FIRMS VIIRS (thermal biomass fire detection)
                    ├── OpenStreetMap Overpass (coastal and urban morphology)
                    └── Google Gemini (natural language citizen heads-up)
                                 │
                                 ▼
                      [ FastAPI REST Service ]
                         ├── GET /api/interpolate
                         ├── GET /api/forecast/{station_id}
                         ├── GET /api/forecast/coordinate
                         └── GET /health
```

---

## Benchmark Results

All models are evaluated on real historical telemetry from the Central Pollution Control Board (CPCB) across Mumbai stations.

### 1. Spatial Interpolation: Spatial GNN vs Inverse Distance Weighting (IDW)
Evaluated via leave-one-station-out cross-validation across the Mumbai monitoring fleet:

| Metric | Baseline IDW | Spatial GNN | Net Gain |
|---|:---:|:---:|:---:|
| MAE (AQI points) | 27.47 | **21.24** | **+22.7% error reduction** |
| RMSE (AQI points) | 36.75 | **27.40** | **+25.4% error reduction** |

*Production checkpoint stored at `backend/models/gnn_best.pt`.*

### 2. Temporal Forecasting: Fast Rolling SARIMA vs Baselines
Evaluated over a 7-day walk-forward horizon with rolling 24-hour forecast steps:

| Station | Baseline (Seasonal-Naive) | Rolling SARIMA | Status |
|---|:---:|:---:|:---:|
| Chhatrapati Shivaji Airport (T2) | 4.42 | **3.16** | Won by SARIMA (+1.25 pts) |
| Kurla | 13.52 | **9.16** | Won by SARIMA (+4.35 pts) |
| Powai | 10.35 | **7.57** | Won by SARIMA (+2.79 pts) |
| Sion | 13.92 | **12.02** | Won by SARIMA (+1.89 pts) |
| Worli | 10.38 | **4.73** | Won by SARIMA (+5.64 pts) |
| Borivali East | 18.27 | **12.97** | Won by SARIMA (+5.30 pts) |
| **Fleet Average** | **11.81** | **8.27** | **6 / 6 Station Wins (+3.54 pts net)** |

*Model fits in 0.10s to 0.25s per station, eliminating slow batch retraining.*

### 3. Spatio-Temporal Forecasting at Arbitrary Coordinates
Chaining SARIMA station forecasts into the Spatial GNN allows predictions at locations with no monitoring stations. Evaluated via leave-one-station-out backtesting across forecast horizons:

| Horizon | Baseline (IDW Chain) | Shwas (GNN Chain) | Performance Advantage |
|:---:|:---:|:---:|---|
| **h = 1h** | 48.5 MAE | **9.0 MAE** | **81.4% error reduction** |
| **h = 6h** | 50.6 MAE | **9.9 MAE** | **80.4% error reduction** |
| **h = 12h** | 54.1 MAE | **11.7 MAE** | **78.4% error reduction** |
| **h = 24h** | 50.6 MAE | **13.5 MAE** | **73.3% error reduction** |

*Even at a full 24-hour horizon without an on-site physical sensor, the GNN chain achieves 13.5 MAE, closely tracking the theoretical upper bound of an on-site hardware sensor (direct SARIMA achieves 10.3 MAE).*

### 4. Uncertainty Quantification and Calibration
To prevent false confidence in data-sparse zones, predictions output calibrated error bounds:
* SARIMA Confidence Intervals: 85.1% empirical coverage on walk-forward testing (target 95%, average interval width: 35.7 AQI points).
* GNN Monte Carlo Dropout: Multiple forward passes with active dropout estimate epistemic model uncertainty, automatically widening confidence bands in regions far from active sensors.

---

## Datasets and Telemetry Sources

Shwas relies on publicly available, open-access datasets and APIs. No proprietary credentials are required to inspect the code.

1. Central Pollution Control Board (CPCB) Real-Time Portal
   * Source: Open Government Data (OGD) Platform India ([data.gov.in](https://data.gov.in/))
   * Role: Ingests hourly concentrations of PM2.5, PM10, SO2, NO2, CO, O3, and NH3 across 25 monitoring locations in Mumbai.
2. Historical Indian Air Quality Dataset (2015 to 2020)
   * Source: Kaggle / CPCB Archives ([Air Quality Data in India](https://www.kaggle.com/datasets/rohitgr/air-quality-data-in-india))
   * Role: Supplies continuous hourly historical context used to train neural weights and validate walk-forward time-series models.
3. OpenWeatherMap Weather Telemetry
   * Source: Current Weather Data API ([openweathermap.org](https://openweathermap.org/api))
   * Role: Provides surface temperature, humidity, wind speed, and compass direction to compute atmospheric dispersion vectors.
4. NASA FIRMS Active Fire Telemetry
   * Source: NASA Earthdata FIRMS ([firms.modaps.eosdis.nasa.gov](https://firms.modaps.eosdis.nasa.gov/))
   * Sensor: VIIRS (Visible Infrared Imaging Radiometer Suite) SNPP Near Real-Time.
   * Role: Detects active crop burning, biomass combustion, and industrial flares, providing fire counts and Fire Radiative Power (MW).
5. OpenStreetMap Urban Morphology
   * Source: Overpass API ([overpass-api.de](https://overpass-api.de/))
   * Role: Queries coastal boundaries, waterways, and road networks to establish geographic station characteristics.
6. Google Gemini API
   * Source: Google DeepMind ([ai.google.dev](https://ai.google.dev/))
   * Role: Translates multi-sensor telemetry (AQI, wind vectors, fire anomalies, news) into single-sentence natural language citizen summaries.

---

## REST API Reference

The FastAPI service exposes the following endpoints:

### 1. Service Health Check
* `GET /health`
* Response: `{"status": "ok"}`

### 2. Real-Time Spatial Interpolation
* `GET /api/interpolate?lat={lat}&lon={lon}`
* Parameters:
  * `lat` (float, required): Query latitude (18.85 to 19.30 for Mumbai)
  * `lon` (float, required): Query longitude (72.75 to 73.00 for Mumbai)
* Response:
```json
{
  "lat": 19.076,
  "lon": 72.8777,
  "estimated_aqi": 64.5,
  "model": "gnn",
  "stations_used": 25
}
```

### 3. Station Time-Series Forecast
* `GET /api/forecast/{station_id}?steps={steps}&uncertainty={true|false}`
* Parameters:
  * `station_id` (string, required): Station slug (e.g. `kurla-mumbai-mpcb`)
  * `steps` (int, default `24`, range `1-168`): Forecast horizon in hours
  * `uncertainty` (bool, default `false`): Include 95% analytical confidence intervals
* Response:
```json
{
  "station_id": "kurla-mumbai-mpcb",
  "model": "sarima",
  "steps": 24,
  "forecast": [
    {
      "timestamp": "2026-09-30T00:00:00+00:00",
      "aqi": 82.4,
      "aqi_lower": 68.1,
      "aqi_upper": 96.7
    }
  ]
}
```

### 4. Spatio-Temporal Coordinate Forecast
* `GET /api/forecast/coordinate?lat={lat}&lon={lon}&steps={steps}&uncertainty={true|false}`
* Parameters:
  * `lat` (float, required): Query latitude
  * `lon` (float, required): Query longitude
  * `steps` (int, default `24`, range `1-48`): Forecast horizon in hours
  * `uncertainty` (bool, default `false`): Include MC-dropout confidence intervals
* Response:
```json
{
  "lat": 19.076,
  "lon": 72.8777,
  "model": "gnn",
  "steps": 24,
  "stations_used": 25,
  "forecast": [
    {
      "timestamp": "2026-09-30T00:00:00+00:00",
      "aqi": 64.5,
      "category": "Satisfactory",
      "aqi_lower": 54.2,
      "aqi_upper": 74.8,
      "uncertainty_std": 5.25
    }
  ]
}
```

---

## Repository Structure

```
Shwas/
├── README.md                           # Project technical documentation
├── backend/
│   ├── alembic/                        # Database schema migrations
│   │   ├── versions/                   # Migration scripts (stations, readings, AQI)
│   │   └── env.py
│   ├── alembic.ini
│   ├── requirements.txt                # Python backend dependencies
│   ├── app/
│   │   ├── aqi/                        # Official CPCB sub-index breakpoints and math
│   │   ├── attribution/                # OpenWeather, NASA FIRMS, OSM Overpass, Gemini LLM
│   │   ├── forecasting/                # SARIMA forecaster, coordinate spatial chainer, baselines
│   │   ├── ingestion/                  # CPCB client with retry backoff, data cleaner, scheduler
│   │   ├── interpolation/              # Haversine distance, bearing, IDW math, live snapshot
│   │   ├── ml/                         # Spatial GNN architecture, GAT attention, model registry
│   │   ├── models/                     # SQLAlchemy relational schema models
│   │   ├── routers/                    # FastAPI route controllers (interpolate, forecast)
│   │   ├── config.py                   # Pydantic configuration and environment variables
│   │   ├── db.py                       # PostgreSQL engine and session factory
│   │   ├── main.py                     # FastAPI application entrypoint
│   │   └── utils.py                    # Slugification and string utilities
│   ├── evaluate/
│   │   ├── evaluate_forecast.py        # 7-day walk-forward station forecast benchmark
│   │   └── evaluate_interpolation.py   # Spatial leave-one-out cross-validation script
│   ├── models/
│   │   ├── gnn_best.pt                 # Production PyTorch GNN model checkpoint
│   │   └── gnn_checkpoint.pt
│   ├── scripts/
│   │   ├── audit_data_completeness.py  # Health check for station telemetry coverage
│   │   ├── build_station_features.py   # Extracts OSM spatial attributes for all stations
│   │   ├── check_geo_feature_correlation.py # Statistical checks on urban features
│   │   ├── evaluate_coordinate_forecast.py  # Spatio-temporal coordinate backtest runner
│   │   ├── evaluate_uncertainty_calibration.py # Calibration benchmark for CI and MC-dropout
│   │   ├── fetch_live_sample.py        # Diagnostic script for live CPCB API response
│   │   ├── merge_historical.py         # Ingests and cleans Kaggle historical archive
│   │   ├── seed_stations.py            # Seeds Mumbai monitoring station coordinates
│   │   └── train_gnn.py                # GNN training pipeline with Cosine Annealing
│   └── tests/
│       ├── test_attribution.py         # Unit tests for weather vectors and fire telemetry
│       ├── test_calculator.py          # Unit tests for CPCB 16-breakpoint sub-index logic
│       ├── test_cleaner.py             # Unit tests for physical ratio anomaly filters
│       ├── test_forecasting.py         # Unit tests for SARIMA windowing and fit stability
│       ├── test_gnn.py                 # Unit tests for GNN tensor shapes and attention layers
│       ├── test_idw.py                 # Unit tests for Haversine distances and wind weights
│       ├── test_integration_api.py     # End-to-end integration tests on FastAPI routers
│       ├── test_spatial_forecast.py    # Unit tests for coordinate forecast chaining
│       └── test_uncertainty.py         # Unit tests for SARIMA CI and MC-dropout bounds
```

---

## Setup and Local Development

### 1. Prerequisites
* Python 3.10 to 3.12 (or Python 3.14 with CPU PyTorch)
* PostgreSQL 14 or higher

### 2. Environment Configuration
Create a `.env` file in `backend/` based on this template:

```ini
# Central Pollution Control Board (data.gov.in)
CPCB_API_KEY=your_cpcb_api_key_here
CPCB_RESOURCE_ID=3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69

# OpenWeatherMap API
OPENWEATHERMAP_API_KEY=your_openweathermap_api_key_here

# NASA FIRMS Satellite API
FIRMS_MAP_KEY=your_nasa_firms_map_key_here

# PostgreSQL Connection String
DATABASE_URL=postgresql://postgres:password@localhost:5432/shwas_db

# Target City Definition
TARGET_CITY=Mumbai

# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Installation
```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Database Setup and Station Seeding
```bash
# Apply Alembic database migrations
alembic upgrade head

# Seed initial Mumbai monitoring stations metadata
python scripts/seed_stations.py
```

### 5. Running the Application Services

#### Start the FastAPI Server:
```bash
python -m uvicorn app.main:app --reload --port 8000
```
Interactive API documentation will be available at:
* Swagger UI: `http://localhost:8000/docs`
* ReDoc: `http://localhost:8000/redoc`

#### Start the Automated Ingestion Scheduler:
```bash
python app/ingestion/scheduler.py
```
This runs hourly CPCB polling at minute `:10` with automatic backoff and database synchronization.

---

## Verification and Testing

The repository contains an automated test suite with **76 passing unit and integration tests** covering all mathematical, physical, and neural components.

Run the test suite:
```bash
python -m pytest tests/ -v
```

Expected output:
```text
============================= test session starts =============================
collected 76 items

tests/test_attribution.py .......                                        [  9%]
tests/test_calculator.py .............                                   [ 26%]
tests/test_cleaner.py .......                                            [ 35%]
tests/test_forecasting.py ....                                           [ 40%]
tests/test_gnn.py .......                                                [ 50%]
tests/test_idw.py .........                                              [ 61%]
tests/test_integration_api.py ...........                                [ 76%]
tests/test_spatial_forecast.py ......                                    [ 84%]
tests/test_uncertainty.py ............                                   [100%]

============================== 76 passed in 5.87s ==============================
```

---

## Running Model Evaluations

### 1. Spatial GNN Evaluation
Evaluates the trained Graph Neural Network against baseline inverse distance weighting:
```bash
python scripts/evaluate_gnn.py --eval-val
```

### 2. Temporal SARIMA Forecast Evaluation
Runs walk-forward rolling 24-hour evaluation across Mumbai stations:
```bash
python evaluate/evaluate_forecast.py --days 7
```

### 3. Spatio-Temporal Coordinate Forecast Backtest
Runs leave-one-station-out cross-validation testing arbitrary coordinate predictions:
```bash
python scripts/evaluate_coordinate_forecast.py --stations 5 --windows 3
```

### 4. Uncertainty Calibration Evaluation
Checks empirical coverage of SARIMA analytical confidence intervals and GNN MC-dropout bounds:
```bash
python scripts/evaluate_uncertainty_calibration.py
```
