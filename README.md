# Shwas (श्वास)

**Shwas (श्वास)** is an end-to-end spatio-temporal air quality intelligence and municipal exposure platform designed for dense Indian metropolitan areas, built, deployed, and rigorously benchmarked on the municipal sensor fleet of the Mumbai metropolitan region.

Government air quality monitoring networks across Global South megacities face four critical structural barriers:
1. **Spatial Sparsity**: Physical Central Pollution Control Board (CPCB) continuous ambient air monitoring stations (CAAQMS) are separated by 5 to 15 kilometers. Unmonitored residential neighborhoods, industrial pockets, and coastal slums have zero direct hardware coverage.
2. **Temporal Latency & Non-Stationarity**: Standard autoregressive models either struggle with diurnal coastal sea-breeze shifts and rush-hour spikes, or require heavy, multi-hour batch retraining cycles that cannot adapt dynamically.
3. **Lack of Causal & Physical Context**: Raw particulate measurements (e.g., *"PM2.5: 142 µg/m³"*) provide citizens and municipal administrators with zero actionable context regarding pollution origin—whether driven by local vehicular combustion, refinery flue gas, biomass burning, sea spray, or wind stagnation.
4. **Actionability Gap**: Municipalities lack data-driven decision tools to locate where emergency anti-pollution interventions (mist canons, construction halts) are needed or where newly budgeted hardware monitors should be positioned to minimize citywide monitoring uncertainty.

Shwas bridges these gaps by combining **Graph Attention Networks (GAT)** for continuous spatial interpolation, **rolling SARIMAX** with atmospheric weather regressors for rapid hourly forecasting, **multi-modal satellite and chemical ratio heuristics** for causal source attribution, **DBSCAN spatial clustering** for real-time hotspot detection, a **greedy variance-reduction optimizer** for sensor network expansion, and a high-performance **interactive MapLibre GL React web application**.

---

## System Architecture

```
                          [ Ingestion & Data Sanitization ]
   ├── CPCB CAAQMS Real-Time Ingestion (data.gov.in) with exponential backoff
   ├── Historical CAAQMS multi-year archives (Kaggle / CPCB 2015–present)
   ├── Open-Meteo ERA5 atmospheric reanalysis & 16-day numerical weather forecasts
   └── Physical ratio anomaly cleaners (PM2.5/PM10 bounds, negative value rejection)
                                    │
                                    ▼
       ┌────────────────────────────┴─────────────────────────────┐
       ▼                                                          ▼
[ Spatial Modeling Engine ]                                [ Temporal Forecasting Engine ]
 ├── Spatial GNN (Graph Attention Network)                  ├── Rolling Seasonal ARIMA (1, 0, 1)(1, 0, 0)24
 ├── Distance-biased k-NN dynamic topology                  ├── SARIMAX (+5 hourly ERA5 weather regressors)
 └── +22.7% error reduction over baseline IDW               └── +14.0% additional fleet error reduction
       │                                                          │
       └────────────────────────────┬─────────────────────────────┘
                                    ▼
                 [ Chained Spatio-Temporal Predictor ]
                   ├── Forecasts all active stations 24h ahead via SARIMAX
                   ├── Projects future station tensors through Spatial GNN
                   ├── Delivers calibrated 24h forecast for any (lat, lon)
                   └── 73.3% to 81.4% error reduction over baseline chaining
                                    │
                                    ▼
                 [ Uncertainty Quantification Engine ]
                   ├── Analytical 95% confidence intervals from SARIMAX covariance
                   └── Monte Carlo Dropout (epistemic variance) over GNN layers
                                    │
       ┌────────────────────────────┴─────────────────────────────┐
       ▼                                                          ▼
[ Multi-Modal Attribution & Apportionment ]                [ Spatial Analytics & Recommendations ]
 ├── Open-Meteo & OpenWeather (wind vectors, dispersion)    ├── Continuous Mumbai Bounding Box Grid Scan
 ├── NASA FIRMS VIIRS (thermal biomass fire detection)     ├── DBSCAN Spatial Clustering (AQI Hotspots)
 ├── PM2.5/PM10 fine-fraction combustion/dust heuristic    ├── Greedy Variance-Reduction Sensor Placement
 ├── OpenStreetMap Overpass (coastal/urban morphology)     └── 24 BMC Wards Population Exposure (Census 2011)
 └── Google Gemini LLM (natural language citizen heads-up)
                                    │
                                    ▼
                        [ FastAPI REST Backend ]
   ├── GET /api/stations                     ├── GET /api/attribution/{station_id}
   ├── GET /api/interpolate                  ├── GET /api/attribution/{station_id}/apportionment
   ├── GET /api/forecast/{station_id}        ├── GET /api/attribution/city/apportionment
   ├── GET /api/forecast/coordinate          ├── GET /api/analytics/hotspots
   ├── GET /api/wards                        ├── GET /api/recommendations/sensor-placement
   └── GET /health
                                    │
                                    ▼
                  [ Interactive Geospatial Web Application ]
   ├── React 19 + Vite client with real-time SSE / polling orchestration
   ├── MapLibre GL 3D vector map with continuous spatial AQI canvas interpolation
   ├── Interactive BMC administrative ward boundaries & population risk heatmaps
   ├── Station drawer: live multi-pollutants (PM2.5, PM10, NO2, SO2) & fine-fraction ratios
   ├── Lazy-loaded 24-hour SARIMAX forecast charts with analytical confidence intervals
   ├── Real-time source attribution card with wind trajectory backtrack & NASA fire alerts
   └── City overview: stacked cleanest/worst ward cards & CPCB category health modal
```

---

## Benchmark Results

All models are evaluated on real historical and live telemetry from the Central Pollution Control Board (CPCB) across the Mumbai municipal sensor network.

### 1. Spatial Interpolation: Spatial GNN vs Inverse Distance Weighting (IDW)
Evaluated via leave-one-station-out cross-validation across the Mumbai monitoring fleet:

| Metric | Baseline IDW | Spatial GNN (Ours) | Net Gain |
|---|:---:|:---:|:---:|
| **MAE (AQI points)** | 27.47 | **21.24** | **+22.7% error reduction** |
| **RMSE (AQI points)** | 36.75 | **27.40** | **+25.4% error reduction** |

*Production checkpoint stored at `backend/models/gnn_best.pt`.*

### 2. Temporal Forecasting: Fast Rolling SARIMA vs Baselines
Evaluated over a 7-day walk-forward horizon with rolling 24-hour forecast steps:

| Station | Baseline (Seasonal-Naive) | Rolling SARIMA | Performance |
|---|:---:|:---:|:---:|
| Chhatrapati Shivaji Airport (T2) | 4.42 | **3.16** | Won by SARIMA (+1.25 pts) |
| Kurla | 13.52 | **9.16** | Won by SARIMA (+4.35 pts) |
| Powai | 10.35 | **7.57** | Won by SARIMA (+2.79 pts) |
| Sion | 13.92 | **12.02** | Won by SARIMA (+1.89 pts) |
| Worli | 10.38 | **4.73** | Won by SARIMA (+5.64 pts) |
| Borivali East | 18.27 | **12.97** | Won by SARIMA (+5.30 pts) |
| **Fleet Average** | **11.81** | **8.27** | **6 / 6 Station Wins (+3.54 pts net)** |

*Model fits in 0.10s to 0.25s per station, completely eliminating multi-hour batch retraining.*

### 3. Weather-Aware Forecasting: SARIMAX vs Plain SARIMA vs Baseline
Evaluated on full walk-forward testing incorporating five exogenous ERA5 weather features (temperature, relative humidity, wind speed, surface pressure, precipitation):

| Station | Baseline (Seasonal-Naive) | Plain SARIMA | SARIMAX (+Weather) | Weather Impact |
|---|:---:|:---:|:---:|:---:|
| Chhatrapati Shivaji Airport (T2) | 4.42 | 3.16 | **2.92** | Won by SARIMAX (+0.24 pts) |
| Kurla | 13.52 | 9.16 | **7.18** | Won by SARIMAX (+1.98 pts) |
| Powai | 10.35 | 7.57 | **6.79** | Won by SARIMAX (+0.78 pts) |
| Sion | 13.92 | 12.02 | **8.37** | Won by SARIMAX (+3.65 pts) |
| Worli | 10.38 | 4.73 | **4.07** | Won by SARIMAX (+0.66 pts) |
| Borivali East | 18.27 | **12.97** | 13.35 | Won by SARIMA (-0.38 pts) |
| **Fleet Average** | **11.81** | **8.27** | **7.11** | **5 / 6 Wins (+14.0% error reduction)** |

### 4. Spatio-Temporal Forecasting at Arbitrary Coordinates
Chaining station forecasts into the Spatial GNN allows predictions at locations with no physical sensors. Evaluated via leave-one-station-out backtesting across horizons:

| Horizon | Baseline (IDW Chain) | Shwas (GNN Chain) | Performance Advantage |
|:---:|:---:|:---:|---|
| **h = 1h** | 48.5 MAE | **9.0 MAE** | **81.4% error reduction** |
| **h = 6h** | 50.6 MAE | **9.9 MAE** | **80.4% error reduction** |
| **h = 12h** | 54.1 MAE | **11.7 MAE** | **78.4% error reduction** |
| **h = 24h** | 50.6 MAE | **13.5 MAE** | **73.3% error reduction** |

*Even at a full 24-hour horizon without an on-site hardware sensor, the GNN chain achieves 13.5 MAE, closely tracking the theoretical upper bound of an on-site hardware sensor (direct on-site SARIMA achieves 10.3 MAE).*

### 5. Uncertainty Quantification and Calibration
To prevent false precision in data-sparse zones, predictions output calibrated error bounds:
* **SARIMA Confidence Intervals**: 85.1% empirical coverage on walk-forward testing (target 95%, average interval width: 35.7 AQI points).
* **GNN Monte Carlo Dropout**: Multiple forward passes with active dropout estimate epistemic model uncertainty, automatically widening confidence bands in regions far from active sensors.

---

## Datasets and Telemetry Sources

Shwas operates on open-access scientific datasets and APIs. No proprietary credentials are required to inspect or evaluate the code:

1. **Central Pollution Control Board (CPCB) Real-Time Portal**
   * *Source*: Open Government Data (OGD) Platform India ([data.gov.in](https://data.gov.in/))
   * *Role*: Ingests hourly concentrations of PM2.5, PM10, SO2, NO2, CO, O3, and NH3 across 25 CAAQMS monitoring locations in Mumbai.
2. **Historical Indian Air Quality Dataset (2015 to Present)**
   * *Source*: Kaggle / CPCB Archives ([Air Quality Data in India](https://www.kaggle.com/datasets/rohitgr/air-quality-data-in-india))
   * *Role*: Supplies continuous hourly historical context used to train neural weights and validate walk-forward time-series models.
3. **Open-Meteo Weather Archive and Forecast API**
   * *Source*: Open-Meteo ([open-meteo.com](https://open-meteo.com/))
   * *Role*: Provides historical ERA5 atmospheric reanalysis (1940 to present) for model training and 16-day hourly forecasts for exogenous time-series inference (temperature, humidity, wind speed, pressure, precipitation) without requiring API keys.
4. **OpenWeatherMap Weather Telemetry**
   * *Source*: Current Weather Data API ([openweathermap.org](https://openweathermap.org/api))
   * *Role*: Provides real-time surface weather to compute live atmospheric dispersion vectors.
5. **NASA FIRMS Active Fire Telemetry**
   * *Source*: NASA Earthdata FIRMS ([firms.modaps.eosdis.nasa.gov](https://firms.modaps.eosdis.nasa.gov/))
   * *Sensor*: VIIRS (Visible Infrared Imaging Radiometer Suite) SNPP Near Real-Time.
   * *Role*: Detects active crop burning, biomass combustion, and industrial flares, providing fire counts and Fire Radiative Power (MW).
6. **OpenStreetMap Urban Morphology**
   * *Source*: Overpass API ([overpass-api.de](https://overpass-api.de/))
   * *Role*: Queries coastal boundaries, waterways, and road networks to establish geographic station characteristics.
7. **Google Gemini API**
   * *Source*: Google DeepMind ([ai.google.dev](https://ai.google.dev/))
   * *Role*: Translates multi-sensor telemetry (AQI, wind vectors, fire anomalies, news) into single-sentence natural language citizen summaries.
8. **Municipal Ward Boundaries and Census 2011 Population**
   * *Source*: Bharatlas Open Administrative Boundaries ([bharatlas.com](https://bharatlas.com/)) and Census of India 2011
   * *Role*: Supplies GeoJSON polygon boundaries for all 24 Brihanmumbai Municipal Corporation (BMC) administrative wards along with ward-level Census 2011 population counts for municipal health risk exposure mapping.

---

## Interactive Geospatial Frontend

The frontend is built with **React 19**, **Vite**, and **MapLibre GL**, engineered for high rendering performance and dynamic state management:

* **Real-Time MapLibre GL Vector Map**: Renders Mumbai's coastline, road networks, 25 CPCB monitoring stations, and 24 BMC administrative ward polygons with GPU-accelerated styling.
* **Continuous Spatial AQI Interpolation**: Overlays a continuous spatial raster/heatmap calculated via Spatial GNN and live station weights, showing gradients across unmonitored neighborhoods.
* **Station Drawer & Multi-Pollutant Metrics**: Clicking any station opens an inspection drawer displaying:
  * Calculated sub-index AQI and CPCB severity badge.
  * Live readings: $\text{PM}_{2.5}$, $\text{PM}_{10}$, $\text{NO}_2$, and $\text{SO}_2$ with timestamp of last update.
  * Fine-fraction ratio ($\text{PM}_{2.5} / \text{PM}_{10}$) with source classification (combustion-dominated vs. road dust vs. mixed background).
* **Lazy-Loaded SARIMAX 24h Forecast Chart**: On-demand hourly time-series chart with upper and lower 95% analytical confidence bounds.
* **Multi-Modal Causal Attribution Panel**: Live wind direction vectors, NASA FIRMS active fire counts within 50 km, and Gemini LLM natural language air quality summary.
* **Ward Exposure Analysis & Stacked Cards**: Sidebar displays cleanly formatted Cleanest vs. Most Polluted stations with agency badges (`MPCB`, `IITM`, `BMC`), search/filtering, and total population counts exposed to each CPCB category.
* **AQI Guide Modal**: Quick reference modal detailing Indian National AQI bands (0–50 Good, 51–100 Satisfactory, 101–200 Moderate, 201–300 Poor, 301–400 Very Poor, 401–500+ Severe).

---

## REST API Reference

The FastAPI service exposes the following endpoints:

### 1. Service Health Check
* `GET /health`
* Response: `{"status": "ok"}`

### 2. Live Stations with Multi-Pollutants
* `GET /api/stations`
* Returns all active monitoring stations with live calculated AQI, individual pollutant readings ($\text{PM}_{2.5}$, $\text{PM}_{10}$, $\text{NO}_2$, $\text{SO}_2$), coordinates, ward names, and reporting agencies.
* Response:
```json
[
  {
    "id": "kurla-mumbai-mpcb",
    "name": "Kurla, Mumbai - MPCB",
    "lat": 19.065,
    "lon": 72.879,
    "ward": "L",
    "agency": "MPCB",
    "aqi": 101.0,
    "pm25": 42.5,
    "pm10": 98.2,
    "no2": 31.4,
    "so2": 12.1,
    "updated_at": "2026-10-02T10:08:00+00:00"
  }
]
```

### 3. Real-Time Spatial Interpolation
* `GET /api/interpolate?lat={lat}&lon={lon}`
* Parameters:
  * `lat` (float, required): Query latitude (18.85 to 19.35 for Mumbai)
  * `lon` (float, required): Query longitude (72.75 to 73.05 for Mumbai)
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

### 4. Station Time-Series Forecast
* `GET /api/forecast/{station_id}?steps={steps}&uncertainty={true|false}`
* Parameters:
  * `station_id` (string, required): Station slug (e.g., `kurla-mumbai-mpcb`)
  * `steps` (int, default `24`, range `1-168`): Forecast horizon in hours
  * `uncertainty` (bool, default `false`): Include 95% analytical confidence intervals
* Response:
```json
{
  "station_id": "kurla-mumbai-mpcb",
  "model": "sarimax",
  "steps": 24,
  "forecast": [
    {
      "timestamp": "2026-10-02T11:00:00+00:00",
      "aqi": 82.4,
      "aqi_lower": 68.1,
      "aqi_upper": 96.7
    }
  ]
}
```

### 5. Spatio-Temporal Coordinate Forecast
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
  "model": "gnn_chained",
  "steps": 24,
  "stations_used": 25,
  "forecast": [
    {
      "timestamp": "2026-10-02T11:00:00+00:00",
      "aqi": 64.5,
      "category": "Satisfactory",
      "aqi_lower": 54.2,
      "aqi_upper": 74.8,
      "uncertainty_std": 5.25
    }
  ]
}
```

### 6. Municipal Ward-Level Population Exposure
* `GET /api/wards`
* Calculates live population-weighted exposure across all 24 BMC administrative wards based on Census 2011 figures.
* Response:
```json
{
  "status": "ok",
  "stations_used": 25,
  "wards": [
    {
      "ward_id": "E",
      "ward_name": "Byculla",
      "population": 393286,
      "census_year": 2011,
      "lat": 18.973,
      "lon": 72.834,
      "aqi": 121.2,
      "category": "Moderate",
      "method": "gnn"
    }
  ],
  "population_by_category": {
    "Moderate": 3145880,
    "Satisfactory": 9296493
  },
  "total_population": 12442373
}
```

### 7. Multi-Modal Causal Attribution
* `GET /api/attribution/{station_id}`
* Combines wind telemetry, back-trajectories, NASA FIRMS active fires, and Gemini LLM synthesis.
* Response:
```json
{
  "station_id": "chembur-mumbai-mpcb",
  "station_name": "Chembur, Mumbai - MPCB",
  "aqi": 118.0,
  "category": "Moderate",
  "dominant_pollutant": "PM2.5",
  "wind": {
    "speed_mps": 3.4,
    "direction_deg": 82,
    "direction_label": "ENE"
  },
  "active_fires_nearby": 0,
  "explanation": "Air is moderate near Chembur today with elevated PM2.5, but an ENE breeze under scattered clouds is keeping particulate dispersion decent."
}
```

### 8. Physical Source Apportionment
* `GET /api/attribution/{station_id}/apportionment`
* Computes rolling 24-hour $\text{PM}_{2.5} / \text{PM}_{10}$ fine-fraction ratios to classify dominant emission sources:
  * `combustion_dominated` ($\text{ratio} \ge 0.65$): Vehicle exhaust, refinery flue gas, biomass burning.
  * `mixed` ($0.40 \le \text{ratio} < 0.65$): General urban background.
  * `dust_dominated` ($\text{ratio} \le 0.40$): Road dust resuspension, construction debris, marine aerosol.
* `GET /api/attribution/city/apportionment`
* Aggregates fine-fraction classifications citywide across all active stations.

### 9. Real-Time Spatial Hotspot Detection
* `GET /api/analytics/hotspots?threshold=100.0&z=1.0`
* Uses DBSCAN spatial clustering over continuous grid scans to identify localized high-pollution clusters.
* Response:
```json
[
  {
    "lat": 19.068,
    "lon": 72.875,
    "ward_id": "L",
    "ward_name": "Kurla",
    "population": 902235,
    "estimated_aqi": 142.3,
    "uncertainty_std": 6.8,
    "lcb": 135.5,
    "lcb_category": "Moderate",
    "method": "gnn"
  }
]
```

### 10. Optimal Sensor Placement Recommendations
* `GET /api/recommendations/sensor-placement?top_k=5&exclusion_radius_km=2.0`
* Executes a greedy variance-reduction algorithm to rank optimal candidate sites for deploying new CAAQMS monitors to minimize citywide spatial interpolation uncertainty.
* Response:
```json
[
  {
    "lat": 19.182,
    "lon": 72.845,
    "ward_id": "P/N",
    "ward_name": "Malad",
    "population": 943776,
    "estimated_aqi": 88.4,
    "uncertainty_std": 14.2,
    "nearest_station_distance_km": 4.85,
    "score": 0.892
  }
]
```

---

## Repository Structure

```
Shwas/
├── README.md                           # Comprehensive technical platform documentation
├── backend/
│   ├── alembic/                        # Database schema migrations
│   │   ├── versions/                   # Migration scripts (stations, readings, AQI)
│   │   └── env.py
│   ├── alembic.ini
│   ├── requirements.txt                # Python backend dependencies
│   ├── app/
│   │   ├── analytics/                  # Spatial grid scan, DBSCAN hotspots, sensor placement, ward exposure
│   │   │   ├── geo.py                  # Haversine distance, Shoelace polygon area & centroid math
│   │   │   ├── grid_scan.py            # Mumbai bounding box grid generation and sampling
│   │   │   ├── hotspots.py             # DBSCAN spatial clustering of elevated AQI zones
│   │   │   ├── sensor_placement.py     # Greedy variance-reduction sensor network optimizer
│   │   │   ├── source_apportionment.py # PM2.5/PM10 fine-fraction combustion/dust classifier
│   │   │   └── ward_exposure.py        # 24 BMC wards Census 2011 population risk aggregation
│   │   ├── aqi/                        # Official Indian CPCB sub-index breakpoints and math
│   │   ├── attribution/                # Multi-modal causal attribution engine
│   │   │   ├── attribution_service.py  # Attribution aggregator and synthesiser
│   │   │   ├── fire_client.py          # NASA FIRMS VIIRS satellite thermal anomaly fetcher
│   │   │   ├── llm_explainer.py        # Google Gemini natural language citizen summarizer
│   │   │   ├── news_search.py          # Real-time air quality news context search
│   │   │   ├── open_meteo_client.py    # Open-Meteo ERA5 reanalysis and hourly weather parser
│   │   │   ├── overpass_client.py      # OpenStreetMap Overpass urban morphology client
│   │   │   └── weather_client.py       # OpenWeatherMap surface wind and dispersion client
│   │   ├── forecasting/                # SARIMA/SARIMAX models, spatial chainer, baselines
│   │   │   ├── sarima_model.py         # Rolling SARIMAX with exogenous weather regressors
│   │   │   ├── service.py              # Forecast service orchestration and caching
│   │   │   └── spatial.py              # Spatio-temporal coordinate forecast chainer
│   │   ├── ingestion/                  # CPCB CAAQMS ingestion, anomaly filters, scheduler
│   │   ├── interpolation/              # Haversine distance, bearing, IDW math, live snapshot
│   │   ├── ml/                         # PyTorch Graph Attention Network (GAT) architecture
│   │   ├── models/                     # SQLAlchemy relational database models
│   │   ├── routers/                    # FastAPI route controllers
│   │   │   ├── attribution.py          # /api/attribution endpoints
│   │   │   ├── forecast.py             # /api/forecast endpoints
│   │   │   ├── interpolate.py          # /api/interpolate and /api/stations endpoints
│   │   │   ├── recommendations.py      # /api/recommendations (hotspots, sensor placement)
│   │   │   └── wards.py                # /api/wards endpoint
│   │   ├── config.py                   # Pydantic Settings and environment validation
│   │   ├── db.py                       # PostgreSQL SQLAlchemy engine and session factory
│   │   └── main.py                     # FastAPI application entrypoint and middleware
│   ├── evaluate/
│   │   ├── evaluate_forecast.py        # 7-day walk-forward station forecast benchmark
│   │   └── evaluate_interpolation.py   # Spatial leave-one-out cross-validation benchmark
│   ├── models/
│   │   ├── gnn_best.pt                 # Production PyTorch GNN model checkpoint
│   │   └── gnn_checkpoint.pt
│   ├── scripts/
│   │   ├── audit_data_completeness.py  # Health check for station telemetry coverage
│   │   ├── build_station_features.py   # Extracts OSM spatial attributes for all stations
│   │   ├── evaluate_coordinate_forecast.py # Spatio-temporal coordinate backtest runner
│   │   ├── evaluate_sarimax_weather.py # Walk-forward benchmark for weather-aware SARIMAX
│   │   ├── evaluate_uncertainty_calibration.py # Calibration benchmark for CI and MC-dropout
│   │   ├── load_ward_data.py           # Seeds 24 BMC ward boundaries and Census 2011 populations
│   │   ├── merge_historical.py         # Ingests and cleans Kaggle historical archive
│   │   ├── seed_stations.py            # Seeds Mumbai monitoring station coordinates
│   │   └── train_gnn.py                # GNN training pipeline with Cosine Annealing
│   └── tests/                          # Automated test suite (140+ unit & integration tests)
│       ├── test_attribution.py
│       ├── test_calculator.py
│       ├── test_cleaner.py
│       ├── test_forecasting.py
│       ├── test_geo.py
│       ├── test_gnn.py
│       ├── test_grid_scan.py
│       ├── test_hotspots.py
│       ├── test_idw.py
│       ├── test_integration_api.py
│       ├── test_integration_attribution.py
│       ├── test_integration_recommendations.py
│       ├── test_integration_wards.py
│       ├── test_load_ward_data.py
│       ├── test_open_meteo_client.py
│       ├── test_sarimax_weather.py
│       ├── test_sensor_placement.py
│       ├── test_source_apportionment.py
│       ├── test_spatial_forecast.py
│       └── test_uncertainty.py
└── frontend/                           # React 19 + Vite + MapLibre GL Web Application
    ├── package.json
    ├── vite.config.js
    ├── src/
    │   ├── App.jsx                     # Core dashboard layout, station selection, state sync
    │   ├── App.css
    │   ├── index.css                   # Design tokens, typography, glassmorphism utilities
    │   ├── main.jsx                    # React root entrypoint
    │   ├── components/
    │   │   ├── LeftPanel.jsx           # Cleanest/worst cards, station search, AQI guide modal
    │   │   ├── LeftPanel.css
    │   │   ├── RightPanel.jsx          # Source attribution, wind vectors, NASA fires, news
    │   │   ├── RightPanel.css
    │   │   ├── ShwasMap.jsx            # MapLibre GL map, continuous interpolation, pins, wards
    │   │   ├── ShwasMap.css
    │   │   ├── StationDetail.jsx       # Drawer with PM2.5/PM10/NO2/SO2, ratio, 24h SARIMAX
    │   │   ├── StationDetail.css
    │   │   ├── TimeSlider.jsx          # Interactive timeline playback
    │   │   └── TopBar.jsx              # Status indicators, live telemetry metadata
    │   ├── hooks/
    │   │   └── useLiveData.js          # Polling, lazy forecast fetch, attribution & recommendations
    │   └── utils/
    │       ├── api.js                  # Axios/fetch client for FastAPI backend endpoints
    │       ├── aqi.js                  # Indian National AQI calculations and category colors
    │       └── geo.js                  # Coordinate conversions and GeoJSON utilities
```

---

#### Configure Environment Variables (`backend/.env`):
```ini
# Database Connection String
DATABASE_URL=postgresql://postgres:password@localhost:5432/shwas_db

# Central Pollution Control Board (data.gov.in)
CPCB_API_KEY=your_cpcb_api_key_here
CPCB_RESOURCE_ID=3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69

# Weather & Atmospheric APIs
OPENWEATHERMAP_API_KEY=your_openweathermap_api_key_here

# NASA FIRMS Satellite API (Thermal Anomalies)
FIRMS_MAP_KEY=your_nasa_firms_map_key_here

# Google Gemini API (Citizen Summaries)
GEMINI_API_KEY=your_gemini_api_key_here

# Target City Definition
TARGET_CITY=Mumbai
```

## Verification and Testing

The repository contains a test suite of **140+ unit and integration tests** verifying all geospatial math, CPCB 16-breakpoint sub-index calculators, anomaly filters, GNN tensor dimensions, SARIMAX fitting, source attribution heuristics, recommendation algorithms, and FastAPI endpoints.
