from datetime import datetime
from app.attribution.weather_client import compass_direction
from app.attribution.fire_client import FireDetection
from app.utils import slugify

def test_compass_direction_none():
    assert compass_direction(None) == 'variable/calm'

def test_compass_direction_cardinals():
    assert compass_direction(0.0) == 'N'
    assert compass_direction(360.0) == 'N'
    assert compass_direction(90.0) == 'E'
    assert compass_direction(180.0) == 'S'
    assert compass_direction(270.0) == 'W'

def test_compass_direction_intercardinals():
    assert compass_direction(45.0) == 'NE'
    assert compass_direction(135.0) == 'SE'
    assert compass_direction(225.0) == 'SW'
    assert compass_direction(315.0) == 'NW'

def test_slugify_basic():
    assert slugify('Powai, Mumbai - MPCB') == 'powai-mumbai-mpcb'

def test_slugify_special_characters():
    name = 'Chhatrapati Shivaji Intl. Airport (T2), Mumbai - MPCB'
    assert slugify(name) == 'chhatrapati-shivaji-intl-airport-t2-mumbai-mpcb'

def test_slugify_strip_hyphens():
    assert slugify('--Sample--Name--') == 'sample-name'

def test_fire_detection_instantiation():
    now = datetime.now()
    fire = FireDetection(
        latitude=19.1,
        longitude=72.9,
        distance_km=12.5,
        acquired_at=now,
        frp_mw=15.2,
        confidence='h',
    )
    assert fire.latitude == 19.1
    assert fire.distance_km == 12.5
    assert fire.confidence == 'h'
