from dataclasses import dataclass, field
try:
    from app.aqi.breakpoints import BREAKPOINTS, MIN_PARAMETERS, REQUIRED_ANY_OF
except ImportError:
    from breakpoints import BREAKPOINTS, MIN_PARAMETERS, REQUIRED_ANY_OF
CATEGORY_BANDS = [(0, 50, 'Good'), (51, 100, 'Satisfactory'), (101, 200, 'Moderate'), (201, 300, 'Poor'), (301, 400, 'Very Poor'), (401, 500, 'Severe')]
CO_RAW_SCALE_FACTOR = 0.01

@dataclass
class AQIResult:
    status: str
    aqi: float | None = None
    category: str | None = None
    dominant_pollutant: str | None = None
    sub_indices: dict = field(default_factory=dict)
    reason: str | None = None

def normalize_raw_reading(pollutant: str, raw_value: float) -> float:
    if pollutant == 'CO':
        return raw_value * CO_RAW_SCALE_FACTOR
    return raw_value

def compute_sub_index(pollutant: str, concentration: float) -> float | None:
    if pollutant not in BREAKPOINTS or concentration is None or concentration < 0:
        return None
    for c_low, c_high, i_low, i_high in BREAKPOINTS[pollutant]:
        if c_low <= concentration <= c_high:
            if c_high == c_low:
                return float(i_low)
            fraction = (concentration - c_low) / (c_high - c_low)
            return i_low + fraction * (i_high - i_low)
    last_band = BREAKPOINTS[pollutant][-1]
    return float(last_band[3])

def _category_for(aqi_value: float) -> str:
    for low, high, name in CATEGORY_BANDS:
        if low <= aqi_value <= high:
            return name
    return 'Severe'

def compute_aqi(raw_readings: dict) -> AQIResult:
    valid_raw = {p: c for p, c in raw_readings.items() if p in BREAKPOINTS and c is not None}
    if len(valid_raw) < MIN_PARAMETERS:
        return AQIResult(status='insufficient_data', reason=f'Only {len(valid_raw)} valid parameter(s) reported; minimum {MIN_PARAMETERS} required.')
    if not set(valid_raw.keys()) & REQUIRED_ANY_OF:
        return AQIResult(status='insufficient_data', reason=f'None of {sorted(REQUIRED_ANY_OF)} present among reported parameters {sorted(valid_raw.keys())}.')
    sub_indices = {}
    for pollutant, raw_value in valid_raw.items():
        normalized = normalize_raw_reading(pollutant, raw_value)
        sub_index = compute_sub_index(pollutant, normalized)
        if sub_index is not None:
            sub_indices[pollutant] = round(sub_index, 1)
    if not sub_indices:
        return AQIResult(status='insufficient_data', reason='No valid sub-indices computed.')
    dominant_pollutant = max(sub_indices, key=sub_indices.get)
    aqi_value = sub_indices[dominant_pollutant]
    return AQIResult(status='ok', aqi=round(aqi_value), category=_category_for(aqi_value), dominant_pollutant=dominant_pollutant, sub_indices=sub_indices)
