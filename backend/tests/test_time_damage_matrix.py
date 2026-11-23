"""Combinatorial coverage of reversible clock corruption; ambiguous text stays reviewed."""
import pytest
from app.plans.dates import normalize_clock_minutes,enforce_spoken_time
from app.plans.colloquial_time import resolve_colloquial_ranges
from app.tasks.schemas import TaskInput

@pytest.mark.parametrize('hour',range(24))
@pytest.mark.parametrize('minute',range(60))
@pytest.mark.parametrize('separator',[':', ' : ', '::', ': ', ' :', ': :'])
def test_clock_separator_damage(hour,minute,separator):
    source=f'Завтра в {hour}{separator}{minute:02d} созвон.'
    assert normalize_clock_minutes(source)==f'Завтра в {hour:02d}:{minute:02d} созвон.'

@pytest.mark.parametrize(('suffix','canonical'),[
 ('ут','утра'),('утр','утра'),('утра','утра'),('дн','дня'),('ня','дня'),('день','дня'),('дня','дня'),
 ('веч','вечера'),('вечер','вечера'),('вечера','вечера'),('ноч','ночи'),('ночь','ночи'),('ночью','ночи'),('ночи','ночи')])
@pytest.mark.parametrize('separator',['',' '])
@pytest.mark.parametrize('hour',range(24))
def test_daypart_damage(hour,suffix,canonical,separator):
    assert normalize_clock_minutes(f'Созвон в {hour}:00{separator}{suffix}')==f'Созвон в {hour:02d}:00 {canonical}'

@pytest.mark.parametrize('hour',range(24))
@pytest.mark.parametrize('zeros',[3,4,5])
def test_extra_zero_minutes(hour,zeros):
    assert normalize_clock_minutes(f'В {hour}:'+ '0'*zeros)==f'В {hour:02d}:00'

@pytest.mark.parametrize(('source','expected'),[
 ('с 09 : 00 веч до 11::00вечер','с 21:00 до 23:00'),
 ('с 09.00 вечера до 11.00 вечера','с 21:00 до 23:00'),
 ('с 09:веч до 11:веч','с 21:00 до 23:00'),
 ('с 23:00ночь до 01:00ночью','с 23:00 до 01:00'),
 ('с 12:00день до 13:00дня','с 12:00 до 13:00'),
])
def test_range_families(source,expected):
    assert resolve_colloquial_ranges(source,'Asia/Tomsk')==expected

@pytest.mark.parametrize('source',[
 'Версия 1.05 приложения', 'Купить 12.05 кг краски', 'Отчёт за 12.05',
 'В 2026 году', 'Скидка 18 процентов', 'Купить 6 стульев',
])
def test_quantities_versions_and_dates_are_preserved(source):
    assert normalize_clock_minutes(source)==source

@pytest.mark.parametrize('damaged',['12:77','12.05','12/05','12:00абра','24:00','29:10','12:05:30','12:0:00'])
def test_ai_rewrite_cannot_clear_ambiguous_original_clock(damaged):
    task=TaskInput(title='Тренировка',start='2026-11-27T19:00:00+07:00',end='2026-11-27T20:00:00+07:00')
    unresolved=enforce_spoken_time([task],f'Тренировка в {damaged}.','Asia/Tomsk','Тренировка в 12:05.')
    assert unresolved=={0}

@pytest.mark.parametrize(('source','expected'),[
 ('в 11 : веч','в 11:00 вечера'),
 ('в 11:000веч','в 11:00 вечера'),
 ('в 9 : : 05утр','в 09:05 утра'),
])
def test_combined_damage(source,expected):
    assert normalize_clock_minutes(source)==expected

@pytest.mark.parametrize('hour',range(24))
@pytest.mark.parametrize('minute',range(60))
def test_repeated_minutes_and_damaged_daypart(hour,minute):
    assert normalize_clock_minutes(f'{hour:02d}:{minute:02d} {minute:02d}')==f'{hour:02d}:{minute:02d}'
    assert normalize_clock_minutes(f'{hour:02d}:{minute:02d} 0ня')==f'{hour:02d}:{minute:02d} дня'
