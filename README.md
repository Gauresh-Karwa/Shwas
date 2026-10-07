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

* **Real-Time MapLibre GL Vector Map with Dynamic Context Layers**: Renders Mumbai's coastline, road networks, 25 CPCB monitoring stations, and 24 BMC administrative ward polygons with GPU-accelerated styling. Users can toggle multiple contextual overlays including **Continuous Spatial Heatmaps**, **Census Population Density**, **Slum Coverage**, **NASA Wind/Fires**, and **DBSCAN Hotspots**.
* **Continuous Spatial AQI Interpolation**: A smooth canvas-rendered spatial raster/heatmap calculated via Spatial GNN and live station weights, masking land dynamically and showing gradients across unmonitored neighborhoods.
* **Unified Attribution & Inspection Panel (`RightPanel`)**: Clicking any hardware station *or any arbitrary unmonitored point on the map* slides out a comprehensive inspection drawer displaying:
  * **Calculated Sub-Index AQI & CPCB Severity Badge**: Computed via the official Central Pollution Control Board (CPCB) piecewise linear sub-index formula:
    $$I_p = I_{\text{low}} + \frac{I_{\text{high}} - I_{\text{low}}}{B_{\text{high}} - B_{\text{low}}} \times (C_p - B_{\text{low}}), \qquad \text{Overall AQI} = \max_{p \in \mathcal{P}} I_p$$
    *(where $C_p$ is the pollutant concentration, $[B_{\text{low}}, B_{\text{high}}]$ is the breakpoint category bracket, $[I_{\text{low}}, I_{\text{high}}]$ is the AQI sub-index bracket, and $\mathcal{P}$ contains at least 3 criteria pollutants with mandatory $\text{PM}_{2.5}$ or $\text{PM}_{10}$)*.
  * **Dynamic Pollutant Bars (`PollutantsBars`)**: A visual breakdown of live criteria pollutants ($\text{PM}_{2.5}$, $\text{PM}_{10}$, $\text{NO}_2$, and $\text{SO}_2$ in $\mu\text{g/m}^3$). Dynamic gradient bars fill relative to CPCB severity thresholds, automatically flagging the "main driver" of the overall AQI.
  * **Fine-Fraction Combustion vs. Crustal Dust Ratio**: Quantifies the particle size distribution via the dimensionless fine-to-coarse ratio:
    $$\eta = \frac{[\text{PM}_{2.5}]}{[\text{PM}_{10}]} \quad (0 \le \eta \le 1)$$
    - **Combustion-Dominated ($\eta \ge 0.65$)**: Fine particulate dominance characteristic of high-temperature combustion: vehicular tailpipe exhaust (diesel/petrol soot), industrial stack flue gas, biomass burning, and secondary nitrate/sulfate aerosols.
    - **Mixed Urban Background ($0.40 < \eta < 0.65$)**: Intermediate composite blend typical of general metropolitan background air, combining dispersed traffic emissions and ambient urban dust.
    - **Dust-Dominated ($\eta \le 0.40$)**: Coarse particulate dominance driven by mechanical shear and suspension: unpaved road dust, construction and demolition debris, quarry dust, or marine coarse aerosol/sea spray.
  * **Natural Language Explanation (`ExplainCard`)**: Presents the Gemini LLM's plain-English synthesis of the complex telemetry, translating wind trajectories, fire data, and chemical ratios into simple, actionable citizen guidance.
  * **Lazy-Loaded SARIMAX 24h Forecast Chart (`ForecastChart24`)**: On-demand hourly time-series chart with upper and lower 95% analytical confidence bounds. Available for both physical stations and chained predictions at unmonitored map points.
* **Control Dashboard & Ward Exposure Analysis (`LeftPanel`)**: Sidebar displays cleanly formatted Cleanest vs. Most Polluted stations with agency badges (`MPCB`, `IITM`, `BMC`), search/filtering, map overlay toggles, and total population counts exposed to each CPCB category.
* **AQI Guide Modal**: Quick reference modal detailing Indian National AQI bands (0–50 Good, 51–100 Satisfactory, 101–200 Moderate, 201–300 Poor, 301–400 Very Poor, 401–500+ Severe).

---

## REST API Reference

The FastAPI service exposes the following endpoints (interactive OpenAPI documentation available at `/docs`):

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health and liveness check. |
| `GET` | `/api/stations` | Live CAAQMS stations with calculated AQI, criteria pollutants ($\text{PM}_{2.5}$, $\text{PM}_{10}$, $\text{NO}_2$, $\text{SO}_2$), coordinates, ward names, and reporting agencies. |
| `GET` | `/api/interpolate?lat={lat}&lon={lon}` | Continuous spatial AQI estimation via Spatial GNN at arbitrary Mumbai coordinates (`lat`: 18.85–19.35, `lon`: 72.75–73.05). |
| `GET` | `/api/forecast/{station_id}?steps=24&uncertainty=true` | Station-level 24-hour time-series forecast using rolling weather-aware SARIMAX with analytical 95% confidence intervals. |
| `GET` | `/api/forecast/coordinate?lat={lat}&lon={lon}&steps=24` | Spatio-temporal chained forecast at unmonitored coordinates with MC-dropout uncertainty bounds. |
| `GET` | `/api/wards` | Real-time population exposure aggregation across all 24 BMC administrative wards based on Census 2011 figures. |
| `GET` | `/api/attribution/{station_id}` | Multi-modal causal attribution combining wind vectors, NASA FIRMS active fire proximity checks, and Gemini LLM synthesis. |
| `GET` | `/api/attribution/{station_id}/apportionment` | Rolling 24-hour fine-fraction ratio $\eta = \frac{\overline{[\text{PM}_{2.5}]}_{24\text{h}}}{\overline{[\text{PM}_{10}]}_{24\text{h}}}$ classifying combustion ($\eta \ge 0.65$) vs. mixed ($0.40 < \eta < 0.65$) vs. dust ($\eta \le 0.40$) sources. |
| `GET` | `/api/attribution/city/apportionment` | Citywide fine-fraction source apportionment summary across the monitoring fleet. |
| `GET` | `/api/analytics/hotspots?threshold=100&z=1.0` | Real-time DBSCAN spatial clustering of continuous grid scans to identify localized high-pollution clusters. |
| `GET` | `/api/recommendations/sensor-placement?top_k=5` | Greedy variance-reduction optimizer ranking top candidate sites for new sensor deployment to minimize spatial interpolation uncertainty. |

---

## Repository Structure

```
Shwas/
├── backend/                            # Python FastAPI backend service
│   ├── alembic/                        # Relational database schema migrations
│   ├── app/                            # Application source package
│   │   ├── analytics/                  # Spatial grid scan, DBSCAN hotspots, sensor placement, ward exposure
│   │   ├── aqi/                        # Official Indian CPCB sub-index breakpoints and math
│   │   ├── attribution/                # Multi-modal causal attribution (wind, NASA FIRMS, Gemini LLM)
│   │   ├── forecasting/                # Rolling SARIMA/SARIMAX models and coordinate spatial chainer
│   │   ├── ingestion/                  # CPCB CAAQMS ingestion, physical anomaly filters, and scheduler
│   │   ├── interpolation/              # Haversine distance, bearing, IDW math, and live snapshots
│   │   ├── ml/                         # PyTorch Graph Attention Network (GAT) spatial architecture
│   │   ├── models/                     # SQLAlchemy relational schema models
│   │   └── routers/                    # FastAPI REST route controllers
│   ├── evaluate/                       # Walk-forward spatial and temporal benchmark suites
│   ├── models/                         # Serialized PyTorch neural model weights and checkpoints
│   ├── scripts/                        # Data seeding, OSM feature extraction, and evaluation runners
│   └── tests/                          # Automated unit and end-to-end integration test suite
└── frontend/                           # React 19 + Vite + MapLibre GL web application
    └── src/                            # Client source code
        ├── assets/                     # Static media and brand vector assets
        ├── components/                 # MapLibre map, station drawer, sidebars, and modals
        ├── data/                       # Seed station metadata and municipal ward GeoJSON boundaries
        ├── hooks/                      # Custom React hooks for real-time telemetry and state sync
        └── utils/                      # REST API client, CPCB sub-index math, and geo utilities
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
