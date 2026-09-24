# Shwas (श्वास)

Shwas is an intelligent spatio-temporal air quality intelligence platform designed for Indian metropolitan regions, pilot tested on the Mumbai municipal sensor network. 

The platform addresses three core limitations of traditional air quality monitoring:
1. Spatial sparsity: Continuous spatial estimation for unmonitored coordinates using Graph Neural Networks.
2. Temporal dynamics: Sub-second 24-hour ahead forecasting using seasonal autoregressive modeling.
3. Actionable attribution: Translating raw particulate numbers into plain English causal explanations combining wind trajectories, satellite thermal anomalies, and urban morphology.

---

## Architecture Overview

Shwas decouples complex spatio-temporal dynamics into dedicated, benchmarked components:

```
[ Data Ingestion & Sanitization ]
   ├── CPCB real-time API (data.gov.in)
   ├── Historical multi-year Kaggle dataset
   └── Physics-based anomaly cleaner (spread ratios, missing values)
          │
          ▼
[ Spatial Modeling Engine ] ──────────────► [ Temporal Forecasting Engine ]
   ├── Spatial GNN (Graph Attention Network)     ├── Seasonal ARIMA (1, 0, 1)(1, 0, 0)24
   ├── Distance-biased k-NN topology             ├── Rolling 14-day adaptive window
   └── 22.7% error reduction over IDW            └── 100% win rate across Mumbai stations
          │                                              │
          └──────────────────────┬───────────────────────┘
                                 ▼
                 [ Multi-Modal Attribution Engine ]
                    ├── OpenWeatherMap (wind vectors and dispersion)
                    ├── NASA FIRMS VIIRS (satellite biomass fire detection)
                    ├── OpenStreetMap Overpass (roads, water, industrial zones)
                    └── Google Gemini (conversational natural language explainer)
```

---

## Datasets and External APIs

Shwas integrates open data repositories and public satellite telemetry. No proprietary or sensitive credentials are embedded in this repository.

### 1. Central Pollution Control Board (CPCB) Real-Time Telemetry
* Source: Open Government Data (OGD) Platform India
* Portal: [data.gov.in](https://data.gov.in/)
* Resource Endpoint: [Real-time Air Quality Index API](https://data.gov.in/resource/real-time-air-quality-index)
* Role: Ingests hourly pollutant concentrations (PM2.5, PM10, SO2, NO2, CO, O3, NH3) across all monitoring stations in the target region.

### 2. Historical Indian Air Quality Dataset (2015 to 2020)
* Source: Kaggle (Curated by Rohit Gupta from official CPCB archives)
* Dataset Link: [Air Quality Data in India (Kaggle)](https://www.kaggle.com/datasets/rohitgr/air-quality-data-in-india)
* Role: Provides multi-year continuous hourly context (`station_hour.csv` and `mumbai_station_hour.csv`) for training deep neural architectures and evaluating walk-forward forecasts.

### 3. OpenWeatherMap Weather Telemetry
* Service: Current Weather and Wind Data API
* Portal: [openweathermap.org/api](https://openweathermap.org/api)
* Role: Supplies local surface temperature, atmospheric humidity, wind speed, and wind direction degrees to compute dispersion vectors and upwind pollutant drift.

### 4. NASA FIRMS Active Fire Satellite Telemetry
* Service: NASA Earthdata Fire Information for Resource Management System (FIRMS)
* Portal: [firms.modaps.eosdis.nasa.gov](https://firms.modaps.eosdis.nasa.gov/api/area/)
* Sensor: VIIRS (Visible Infrared Imaging Radiometer Suite) SNPP Near Real-Time
* Role: Detects active crop burning, biomass combustion, and industrial flares within regional radiuses, calculating Fire Radiative Power (FRP in MW).

### 5. OpenStreetMap Urban Morphology via Overpass API
* Service: OpenStreetMap Overpass Query Engine
* Portal: [overpass-api.de](https://overpass-api.de/)
* Role: Calculates station-level urban physical attributes, including distance to coastline/water bodies, highway network density, industrial zones, and construction activity.

### 6. Google Gemini AI API
* Service: Google DeepMind Gemini API
* Portal: [ai.google.dev](https://ai.google.dev/)
* Role: Synthesizes multi-source telemetry (weather, fires, AQI, news) into single-sentence natural language summaries for public consumption.

---

## Key Modules and Engineering Progress

### 1. Ingestion, Cleaning, and CPCB AQI Calculation
* Location: `backend/app/ingestion/`, `backend/app/aqi/`
* Automated cleaner: Detects physically implausible spreads between minimum and maximum hourly sensor values using dynamic ratio thresholds. Rejects negative concentration values and handles missing sensor channels gracefully.
* Official CPCB engine: Implements the exact 16-breakpoint piecewise linear interpolation algorithm published by the Central Pollution Control Board. Automatically normalizes carbon monoxide units between milligrams and micrograms, identifies the dominant pollutant, and assigns official health categories (Good, Satisfactory, Moderate, Poor, Very Poor, Severe).

### 2. Spatial Interpolation: Spatial GNN vs Baselines
* Location: `backend/app/ml/`, `backend/app/interpolation/`, `backend/scripts/`
* Model: Custom Spatial Graph Neural Network (`SpatialGNN`) built in PyTorch.
* Graph topology: Dynamically generated k-nearest neighbors (k-NN) graph using Haversine spherical distance metrics.
* Attention mechanism: Multi-head Spatial Graph Attention (`SpatialGATLayer`) using query-key scaled dot-product attention biased by logarithmic physical distance.
* Features: Node features incorporate normalized coordinates, current AQI, 1-hour lag, 3-hour lag, and cyclical sine/cosine temporal encodings for hour of day and day of week.
* Spatial Evaluation (Leave-One-Out Holdout on Mumbai Fleet):

| Metric | IDW Baseline | Spatial GNN | Improvement |
|---|:---:|:---:|:---:|
| MAE (AQI points) | 27.47 | **21.24** | **+22.7% gain** |
| RMSE (AQI points) | 36.75 | **27.40** | **+25.4% gain** |

Saved checkpoint weights: `backend/models/gnn_best.pt`

### 3. Temporal Forecasting: Fast Rolling SARIMA vs Baselines
* Location: `backend/app/forecasting/`, `backend/evaluate/`
* Model: Seasonal Autoregressive Integrated Moving Average: `SARIMA(1, 0, 1)(1, 0, 0)24`.
* Formulation: Captures immediate hour-to-hour persistence via AR(1), diurnal traffic and solar cycles via seasonal AR(1) at lag 24, and shock attenuation via MA(1) without explosive differencing drift.
* Rolling windowing: Operates on a sliding 14-day history (336 hourly observations). Fits in 0.10s to 0.25s per station, eliminating the need for slow multi-minute batch training.
* Baseline comparison: Tested against a seasonal-naive persistence baseline (same hour yesterday) and Facebook Prophet.
* Walk-Forward Fleet Evaluation (24-hour horizon, 7-day walk-forward holdout):

| Station | Baseline MAE | SARIMA MAE | Net Gain | Status |
|---|:---:|:---:|:---:|:---:|
| Chhatrapati Shivaji Airport (T2) | 4.42 | **3.16** | +1.25 pts | Won by SARIMA |
| Kurla | 13.52 | **9.16** | +4.35 pts | Won by SARIMA |
| Powai | 10.35 | **7.57** | +2.79 pts | Won by SARIMA |
| Sion | 13.92 | **12.02** | +1.89 pts | Won by SARIMA |
| Worli | 10.38 | **4.73** | +5.64 pts | Won by SARIMA |
| Borivali East | 18.27 | **12.97** | +5.30 pts | Won by SARIMA |
| **Fleet Average** | **11.81** | **8.27** | **+3.54 pts** | **6 / 6 Station Wins** |

Fallback strategy: If a newly added sensor station has fewer than 7 days of historical readings, the system falls back to the Seasonal-Naive baseline until sufficient history accumulates.

### 4. Causal Attribution and Environmental Features
* Location: `backend/app/attribution/`
* Wind vector calculation: Computes 16-point compass directions and assesses whether a target coordinate is downwind from major industrial clusters or traffic corridors.
* Thermal detection: Queries NASA VIIRS satellites for active thermal signatures within regional bounds, reporting fire counts and aggregate radiative power.
* Natural language explainer: Structured prompt fed to Gemini Flash models to translate complex sensor numbers into a single clear, friendly sentence for everyday citizens.

---

## Repository Structure

```
Shwas/
├── README.md                           # Comprehensive project documentation
├── requirements.txt                    # Root environment pointers
├── backend/
│   ├── alembic/                        # Database schema migrations
│   │   ├── versions/                   # Migration versions (tables, geo features)
│   │   └── env.py
│   ├── alembic.ini
│   ├── requirements.txt                # Python backend dependencies
│   ├── app/
│   │   ├── aqi/                        # CPCB sub-index math and breakpoints
│   │   ├── attribution/                # Weather, NASA FIRMS, OSM Overpass, LLM explainer
│   │   ├── forecasting/                # SARIMA forecaster and seasonal-naive baseline
│   │   ├── ingestion/                  # CPCB scrapers, data cleaner, scheduler
│   │   ├── interpolation/              # Haversine distance, bearing, IDW math
│   │   ├── ml/                         # Spatial GNN architecture (GAT layers, k-NN graph)
│   │   ├── models/                     # SQLAlchemy relational database models
│   │   ├── routers/                    # FastAPI route definitions
│   │   ├── config.py                   # Pydantic environment configuration
│   │   ├── db.py                       # PostgreSQL engine and session management
│   │   └── utils.py                    # Slugification and string utilities
│   ├── evaluate/
│   │   ├── evaluate_forecast.py        # Walk-forward 24h temporal benchmark runner
│   │   └── evaluate_interpolation.py   # Spatial interpolation benchmark runner
│   ├── models/
│   │   ├── gnn_best.pt                 # Production-trained GNN model weights
│   │   └── gnn_checkpoint.pt
│   ├── scripts/
│   │   ├── audit_data_completeness.py  # Health check for sensor telemetry completeness
│   │   ├── build_station_features.py   # Extracts OSM spatial features for all stations
│   │   ├── evaluate_gnn.py             # Leave-one-out GNN evaluation script
│   │   ├── fetch_live_sample.py        # Live CPCB fetch diagnostic tool
│   │   ├── merge_historical.py         # Merges Kaggle historical data with live records
│   │   ├── seed_stations.py            # Populates Mumbai monitoring station metadata
│   │   └── train_gnn.py                # PyTorch training pipeline with Cosine Annealing
│   └── tests/
│       ├── test_attribution.py         # Tests for wind direction, slugify, fire data
│       ├── test_calculator.py          # Tests for CPCB sub-index algorithms
│       ├── test_cleaner.py             # Tests for outlier cleaner and spread ratios
│       ├── test_forecasting.py         # Tests for SARIMA windowing and predictions
│       ├── test_gnn.py                 # Tests for GNN tensors, layers, and interpolation
│       └── test_idw.py                 # Tests for Haversine math, bearing, IDW weights
├── data/
│   ├── historical/                     # Kaggle historical datasets (git-ignored)
│   └── raw/                            # Ingested raw telemetry JSON dumps
└── frontend/                           # Client interface application directory
```

---

## Setup and Local Development

### 1. Prerequisites
* Python 3.10 or higher
* PostgreSQL 14 or higher

### 2. Environment Configuration
Create a `.env` file inside `backend/` following the template below:

```ini
# Central Pollution Control Board (data.gov.in)
CPCB_API_KEY=your_cpcb_api_key_here
CPCB_RESOURCE_ID=your_data_gov_resource_id_here

# OpenWeatherMap API
OPENWEATHERMAP_API_KEY=your_openweathermap_api_key_here

# NASA FIRMS Active Fire Satellite API
FIRMS_MAP_KEY=your_nasa_firms_map_key_here

# PostgreSQL Database Connection
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

### 4. Database Setup and Migrations
```bash
# Run Alembic migrations to create tables
alembic upgrade head

# Seed initial Mumbai monitoring stations metadata
python scripts/seed_stations.py
```

---

## Verification and Testing

The repository includes a comprehensive, automated test suite with 47 unit tests covering all mathematical, physical, and neural components.

Run the test suite:
```bash
python -m pytest
```

Expected output:
```text
============================= test session starts =============================
collected 47 items

tests/test_attribution.py .......                                        [ 14%]
tests/test_calculator.py .............                                   [ 42%]
tests/test_cleaner.py .......                                            [ 57%]
tests/test_forecasting.py ....                                           [ 65%]
tests/test_gnn.py .......                                                [ 80%]
tests/test_idw.py .........                                              [100%]

============================== 47 passed in 3.34s ==============================
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

---

## Roadmap

1. API Integration: Expose `/api/interpolate` (GNN map inference) and `/api/forecast` (SARIMA station predictions) on the FastAPI service.
2. Frontend Interface: Interactive Mapbox/Leaflet heatmap visualizing the GNN continuous spatial surface and 24-hour station forecast trajectories.
3. Multi-City Expansion: Replicate station feature pipelines and seed scripts for Delhi NCR and Bengaluru.