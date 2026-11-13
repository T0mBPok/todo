from datetime import datetime

from fastapi import HTTPException
import pytest

from app.plans.colloquial_time import resolve_colloquial_ranges

NOW = datetime.fromisoformat('2026-11-11T17:20:00+07:00')
ZONE = 'Asia/Tomsk'


@pytest.mark.parametrize(('source', 'expected'), [
    ('В пятницу работа с 9 до 6.', 'В пятницу работа с 09:00 до 18:00.'),
    ('Сегодня мероприятие с семи тридцати до 9.', 'Сегодня мероприятие с 19:30 до 21:00.'),
    ('Сегодня мероприятие с 7:30 до девяти.', 'Сегодня мероприятие с 19:30 до 21:00.'),
    ('Сегодня тренировка с 11:30 до 12:30.', 'Сегодня тренировка с 11:30 до 12:30.'),
    ('В субботу волейбол с 11:0 до 12:00.', 'В субботу волейбол с 11:0 до 12:00.'),
    ('Завтра концерт с семи тридцати до девяти вечера.', 'Завтра концерт с 19:30 до 21:00.'),
    ('Завтра занятие с 7 утра до девяти.', 'Завтра занятие с 07:00 до 09:00.'),
    ('Отпуск с 3 до 6 ноября.', 'Отпуск с 3 до 6 ноября.'),
])
def test_colloquial_ranges(source, expected):
    assert resolve_colloquial_ranges(source, ZONE, now=NOW) == expected


@pytest.mark.parametrize(('source', 'expected'), [
    ('Завтра мероприятие с семи тридцати до девяти.', ('мероприятие', '07:30–09:00', '19:30–21:00')),
    ('Сегодня до 07:30 у меня мероприятие на 1,5 часа.', ('мероприятие', 'время окончания', 'Во сколько начинается')),
])
def test_question_identifies_the_ambiguous_event(source, expected):
    with pytest.raises(HTTPException) as error:
        resolve_colloquial_ranges(source, ZONE, now=NOW)
    assert error.value.status_code == 422
    assert all(part in error.value.detail for part in expected)
