from app.ingestion.cleaner import clean_reading, SPREAD_RATIO_THRESHOLD


def test_na_values_become_none():
    """CPCB's 'NA' string must become Python None, not stay as text."""
    result = clean_reading("NA", "NA", "NA")
    assert result.min_value is None
    assert result.max_value is None
    assert result.avg_value is None
    assert result.is_corrected is False  # missing data isn't "corrected", just absent


def test_normal_reading_not_flagged():
    """Real Powai SO2 case: min=8, max=14, avg=10 - ordinary variation."""
    result = clean_reading("8", "14", "10")
    assert result.is_corrected is False
    assert result.avg_value == 10


def test_saharsa_style_high_variance_flagged_but_avg_kept():
    """Real Saharsa PM2.5 case: min=33, max=449, avg=65 - a ~13.6x spread.
    Must be flagged, but avg_value must NOT be discarded, since the AQI
    calculator uses avg_value regardless of the flag."""
    result = clean_reading("33", "449", "65")
    assert result.is_corrected is True
    assert result.avg_value == 65
    assert "13.6x" in result.correction_reason


def test_extreme_spread_kurla_pm25():
    """Real Kurla PM2.5 case: min=1, max=100 - a 100x spread, clearly flagged."""
    result = clean_reading("1", "100", "32")
    assert result.is_corrected is True


def test_moderate_spread_not_over_flagged():
    """Real Bandra Kurla Complex PM2.5 case: min=9, max=38 - a 4.2x spread.
    Should NOT be flagged; this is ordinary hourly fluctuation, not a fault."""
    result = clean_reading("9", "38", "21")
    assert result.is_corrected is False


def test_negative_value_rejected_not_passed_through():
    """A negative concentration is physically impossible - must be
    rejected entirely (set to None), never silently passed to AQI calc."""
    result = clean_reading("-5", "10", "3")
    assert result.avg_value is None
    assert result.is_corrected is True
    assert "negative" in result.correction_reason.lower()


def test_unparseable_value_treated_as_missing():
    """A garbled/unexpected value should be treated as missing, not
    crash the whole ingestion run."""
    result = clean_reading("garbage", "10", "5")
    assert result.min_value is None