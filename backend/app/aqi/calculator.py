"""
AQI calculator — implements CPCB's official sub-index formula and the
rules for combining pollutant sub-indices into one overall AQI value.

Rules (CPCB 2014 standard):
- Sub-index = I_low + [(C - C_low) / (C_high - C_low)] * (I_high - I_low)
- Overall AQI = MAX sub-index across all measured pollutants (not average)
- Minimum 3 pollutant parameters required, and at least one of
  PM10 or PM2.5 must be among them, to compute a valid AQI.
  Otherwise, the result is "insufficient_data".

IMPORTANT UNIT NOTE (found via testing against real Mumbai data, 20 Sep 2026):
The data.gov.in CPCB live resource (3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69)
reports CO avg_value as values like 20-56, which are implausible as mg/m3
(CPCB's own 8-hour NAAQ limit is 2.0 mg/m3; real official CPCB station
reports show ambient CO typically 0.3-0.9 mg/m3). Dividing these raw
values by 100 lands them in that same plausible real-world range.
Working hypothesis: this resource reports CO as (mg/m3 * 100), stored as
a plain integer like the other pollutant fields.
STATUS: NOT YET independently confirmed against CPCB's own official
dashboard/app for the same station+timestamp. CO_RAW_SCALE_FACTOR below
is applied on this hypothesis - verify before relying on this for
anything beyond a hackathon demo, and update this constant if disproven.
"""
from dataclasses import dataclass, field

try:
    from app.aqi.breakpoints import BREAKPOINTS, MIN_PARAMETERS, REQUIRED_ANY_OF
except ImportError:
    from breakpoints import BREAKPOINTS, MIN_PARAMETERS, REQUIRED_ANY_OF

CATEGORY_BANDS = [
    (0, 50, "Good"),
    (51, 100, "Satisfactory"),
    (101, 200, "Moderate"),
    (201, 300, "Poor"),
    (301, 400, "Very Poor"),
    (401, 500, "Severe"),
]

# See module docstring — unconfirmed hypothesis, applied to CO only.
CO_RAW_SCALE_FACTOR = 0.01


@dataclass
class AQIResult:
    status: str  # "ok" or "insufficient_data"
    aqi: float | None = None
    category: str | None = None
    dominant_pollutant: str | None = None
    sub_indices: dict = field(default_factory=dict)
    reason: str | None = None  # populated when status == "insufficient_data"


def normalize_raw_reading(pollutant: str, raw_value: float) -> float:
    """Apply any known unit corrections before breakpoint lookup.
    Currently only CO needs this (see module docstring)."""
    if pollutant == "CO":
        return raw_value * CO_RAW_SCALE_FACTOR
    return raw_value


def compute_sub_index(pollutant: str, concentration: float) -> float | None:
    """Compute the sub-index for one pollutant concentration.
    `concentration` must already be in the units BREAKPOINTS expects
    (i.e. normalize_raw_reading should be applied first by the caller)."""
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
    return "Severe"


def compute_aqi(raw_readings: dict) -> AQIResult:
    """
    raw_readings: dict mapping pollutant_id (e.g. "PM2.5") -> RAW avg_value
    from the CPCB API (float). Pollutants with a missing/"NA" value should
    be omitted from this dict entirely by the caller.

    This function applies normalize_raw_reading() internally, so callers
    should pass raw API values directly, not pre-converted ones.
    """
    valid_raw = {p: c for p, c in raw_readings.items() if p in BREAKPOINTS and c is not None}

    if len(valid_raw) < MIN_PARAMETERS:
        return AQIResult(
            status="insufficient_data",
            reason=f"Only {len(valid_raw)} valid parameter(s) reported; "
                   f"minimum {MIN_PARAMETERS} required.",
        )

    if not (set(valid_raw.keys()) & REQUIRED_ANY_OF):
        return AQIResult(
            status="insufficient_data",
            reason=f"None of {sorted(REQUIRED_ANY_OF)} present among reported "
                   f"parameters {sorted(valid_raw.keys())}.",
        )

    sub_indices = {}
    for pollutant, raw_value in valid_raw.items():
        normalized = normalize_raw_reading(pollutant, raw_value)
        sub_index = compute_sub_index(pollutant, normalized)
        if sub_index is not None:
            sub_indices[pollutant] = round(sub_index, 1)

    if not sub_indices:
        return AQIResult(status="insufficient_data", reason="No valid sub-indices computed.")

    dominant_pollutant = max(sub_indices, key=sub_indices.get)
    aqi_value = sub_indices[dominant_pollutant]

    return AQIResult(
        status="ok",
        aqi=round(aqi_value),
        category=_category_for(aqi_value),
        dominant_pollutant=dominant_pollutant,
        sub_indices=sub_indices,
    )
