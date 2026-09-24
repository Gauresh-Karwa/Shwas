from dataclasses import dataclass
SPREAD_RATIO_THRESHOLD = 10

@dataclass
class CleanedValue:
    min_value: float | None
    max_value: float | None
    avg_value: float | None
    is_corrected: bool = False
    correction_reason: str | None = None

def _parse_or_none(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip().upper() == 'NA':
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None

def clean_reading(raw_min, raw_max, raw_avg) -> CleanedValue:
    min_value = _parse_or_none(raw_min)
    max_value = _parse_or_none(raw_max)
    avg_value = _parse_or_none(raw_avg)
    for name, val in [('min_value', min_value), ('max_value', max_value), ('avg_value', avg_value)]:
        if val is not None and val < 0:
            return CleanedValue(min_value=None, max_value=None, avg_value=None, is_corrected=True, correction_reason=f'Rejected: negative {name} ({val}) is physically invalid.')
    if min_value is not None and max_value is not None and (min_value > 0):
        ratio = max_value / min_value
        if ratio > SPREAD_RATIO_THRESHOLD:
            return CleanedValue(min_value=min_value, max_value=max_value, avg_value=avg_value, is_corrected=True, correction_reason=f'High variance flagged: max/min ratio {ratio:.1f}x exceeds {SPREAD_RATIO_THRESHOLD}x threshold (min={min_value}, max={max_value}).')
    return CleanedValue(min_value=min_value, max_value=max_value, avg_value=avg_value)
