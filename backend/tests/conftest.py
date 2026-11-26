import os
# Unit/API tests use mocked providers; never start an external background exchange.
os.environ['GOOGLE_SYNC_WORKER']='0'

# Historical production regressions contain «tomorrow, Wednesday the 25th».
# Keep their reference date explicit so they remain meaningful after November.
import sys
from datetime import datetime,timezone
import pytest

@pytest.fixture
def november24_clock(monkeypatch):
    class ReferenceDateTime(datetime):
        @classmethod
        def now(cls,tz=None):
            point=cls(2026,11,24,5,0,tzinfo=timezone.utc)
            return point.astimezone(tz) if tz is not None else point.replace(tzinfo=None)
    for name in ('app.plans.ai','app.plans.dates','app.plans.prompts',
                 'app.plans.colloquial_time','app.commands.service','app.commands.context',
                 'test_mixed_numeric_calendar'):
        module=sys.modules.get(name)
        if module is not None and hasattr(module,'datetime'):
            monkeypatch.setattr(module,'datetime',ReferenceDateTime)
