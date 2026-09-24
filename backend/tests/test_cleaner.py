from app.ingestion.cleaner import clean_reading, SPREAD_RATIO_THRESHOLD

def test_na_values_become_none():
    result = clean_reading('NA', 'NA', 'NA')
    assert result.min_value is None
    assert result.max_value is None
    assert result.avg_value is None
    assert result.is_corrected is False

def test_normal_reading_not_flagged():
    result = clean_reading('8', '14', '10')
    assert result.is_corrected is False
    assert result.avg_value == 10

def test_saharsa_style_high_variance_flagged_but_avg_kept():
    result = clean_reading('33', '449', '65')
    assert result.is_corrected is True
    assert result.avg_value == 65
    assert '13.6x' in result.correction_reason

def test_extreme_spread_kurla_pm25():
    result = clean_reading('1', '100', '32')
    assert result.is_corrected is True

def test_moderate_spread_not_over_flagged():
    result = clean_reading('9', '38', '21')
    assert result.is_corrected is False

def test_negative_value_rejected_not_passed_through():
    result = clean_reading('-5', '10', '3')
    assert result.avg_value is None
    assert result.is_corrected is True
    assert 'negative' in result.correction_reason.lower()

def test_unparseable_value_treated_as_missing():
    result = clean_reading('garbage', '10', '5')
    assert result.min_value is None
