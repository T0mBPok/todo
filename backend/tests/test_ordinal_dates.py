from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from app.plans.dates import canonical_date_anchors,normalize_clock_minutes

@pytest.mark.parametrize(('source','expected'),[
 ('На 27-е число работа','На 2026-11-27 работа'),
 ('На 27-го работа','На 2026-11-27 работа'),
 ('27 ноября работа','2026-11-27 работа'),
 ('В пятницу 27-го числа работа','В пятницу 27-го числа работа'),
 ('С 08:00 до 09:00 работа','С 08:00 до 09:00 работа'),
 ('Дело 2026-11-27','Дело 2026-11-27'),
])
def test_explicit_days_are_distinct_from_hours(source,expected):
    assert canonical_date_anchors(source,datetime(2026,11,23).date())==expected


def test_compact_broken_start_clock_requires_an_interval():
    assert normalize_clock_minutes('С 80 до 09:00 работа')=='С 08:00 до 09:00 работа'
    assert normalize_clock_minutes('Купить 80 яблок')=='Купить 80 яблок'
