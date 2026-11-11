from app.core.ai_client import ai_post
import json
import re
from collections import Counter
from datetime import timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.core import config
from app.plans.schemas import PlanOutput
from app.tasks.schemas import TaskInput
from app.plans.dates import ANCHOR, TIME_RANGE, enforce_date_context, enforce_spoken_time
from app.recurrences.speech import apply_spoken_recurrence
from app.plans.prompts import planning_prompt, normalize_transcript, normalization_prompt

class ExtractedPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tasks: list[TaskInput] = Field(max_length=30)
    note: str
    needs_clarification: bool

class AIPlanner:
    def normalize(self, text):
        original = normalize_transcript(text)
        schema = {'type':'object', 'properties':{'text':{'type':'string'}, 'note':{'type':'string'}},
                  'required':['text','note'], 'additionalProperties':False}
        response = ai_post(config.OLLAMA_BASE_URL + '/api/chat', timeout=120,
            json={'model':config.OLLAMA_MODEL, 'stream':False, 'think':False, 'keep_alive':'10m',
                  'format':schema, 'options':{'temperature':0,'num_ctx':8192,'num_predict':1800},
                  'messages':[{'role':'system','content':normalization_prompt()}, {'role':'user','content':original}]})
        response.raise_for_status()
        data = response.json()
        if data.get('done_reason') == 'length':
            return original, ''
        parsed = json.loads(data['message']['content'])
        normalized = parsed.get('text')
        if not isinstance(normalized, str) or not normalized.strip() or len(normalized) > 6500:
            return original, ''
        # A language correction must never silently change explicit numeric times.
        times = lambda value: Counter(re.findall(r'(?<!\d)\d{1,2}:\d{2}(?!\d)', value))
        numbers = lambda value: Counter(re.findall(r'\d+', value))
        if times(original) - times(normalized) or numbers(original) != numbers(normalized):
            return original, ''
        details=re.search(r'(?:в\s+описании|описание(?:\s+задачи)?|детали)\s*[:—-]\s*(.+)',original,re.I|re.S)
        if details and details.group(1).strip().lower() not in normalized.lower():
            normalized += ' Описание: ' + details.group(1).strip()
        return normalized, str(parsed.get('note', ''))[:600]

    def generate(self, request, existing):
        schema = ExtractedPlan.model_json_schema()
        schema['$defs']['TaskInput'].setdefault('required',[]).append('category')
        prompt_schema = None if config.AI_PROVIDER == 'gigachat' else schema
        instructions = planning_prompt(request.timezone, existing, prompt_schema)
        try:
            if config.AI_PROVIDER in {'openrouter', 'gigachat'}:
                normalized = normalize_transcript(request.text)
                instructions += '\nИсправляй очевидные оговорки при извлечении событий и сохраняй исходные даты, время и детали.'
            else:
                normalized, _ = self.normalize(request.text)
            response = ai_post(config.OLLAMA_BASE_URL + '/api/chat', timeout=120,
                json={'model': config.OLLAMA_MODEL, 'stream': False, 'think': False,
                      'keep_alive': '10m', 'format': schema,
                      'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 3000},
                      'messages': [{'role': 'system', 'content': instructions},
                                   {'role': 'user', 'content': normalized + '\nИсходный текст (сохрани все детали для описания): ' + request.text}]})
            response.raise_for_status()
            data = response.json()
            if data.get('done_reason') == 'length':
                raise HTTPException(502, 'План слишком большой. Разделите запрос на несколько частей.')
            parsed = ExtractedPlan.model_validate_json(data['message']['content'])
            if parsed.needs_clarification or not parsed.tasks:
                raise HTTPException(422, parsed.note or 'Уточните день, время и задачу.')
            # Explicit descriptions survive even if transcript normalization drops them.
            detail=re.search(r'(?:в\s+описании|описание(?:\s+задачи)?|детали)\s*[:—-]\s*(.+)',request.text,re.I|re.S)
            if len(parsed.tasks)==1 and detail:
                parsed.tasks[0].description=detail.group(1).strip()[:5000]
            spoken = request._spoken_text or request.text
            date_source = spoken if ANCHOR.search(spoken) else request.text
            parsed.tasks = enforce_date_context(parsed.tasks, date_source, request.timezone)
            # The small model can copy example durations. Apply the documented
            # default in code when the user supplied no duration or end time.
            duration_mentioned = (
                TIME_RANGE.search(spoken) or TIME_RANGE.search(request.text)
                or re.search(r'\b(?:час\w*|минут\w*|секунд\w*|полчаса|полтора|полторы|до)\b',
                             spoken + ' ' + request.text, re.IGNORECASE)
            )
            if not duration_mentioned:
                for task in parsed.tasks:
                    task.end = task.start + timedelta(hours=1)
                # Two events on one day linked by "сразу" share their boundary;
                # an explicitly stated next start determines the unknown duration.
                if 'сразу' in request.text.lower():
                    by_day = {}
                    zone = ZoneInfo(request.timezone)
                    for task in parsed.tasks:
                        by_day.setdefault(task.start.astimezone(zone).date(), []).append(task)
                    for tasks in by_day.values():
                        if len(tasks) == 2:
                            first, second = sorted(tasks, key=lambda task: task.start)
                            if second.start > first.start:
                                first.end = second.start
            if not enforce_spoken_time(parsed.tasks, spoken, request.timezone) and spoken != request.text:
                enforce_spoken_time(parsed.tasks, request.text, request.timezone)
            parsed.tasks = apply_spoken_recurrence(parsed.tasks, request.text, request.timezone)
            zone = ZoneInfo(request.timezone)
            summary = '; '.join(f'{task.title}: {task.start.astimezone(zone):%d.%m %H:%M}–{task.end.astimezone(zone):%H:%M}' for task in parsed.tasks)
            note = 'Понял: ' + summary + '.'
            if any(task.recurrence for task in parsed.tasks):
                note += ' Повторяющиеся события продолжаются без даты окончания.'
            if normalized != request.text:
                note += ' Нормализованный текст: ' + normalized
            if not duration_mentioned:
                note += ' Без указанной длительности — 60 минут; для связанных задач «сразу после» конец взят из начала следующей.'
            return PlanOutput(tasks=parsed.tasks, note=note, normalized_text=normalized)

        except httpx.TimeoutException as error:
            raise HTTPException(504, 'Qwen не ответила вовремя. Попробуйте ещё раз или сократите запрос.') from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise HTTPException(503, f'Модель {config.OLLAMA_MODEL} не найдена в Ollama.') from error
            raise HTTPException(502, 'Ошибка локальной Ollama. Проверьте её состояние.') from error
        except httpx.RequestError as error:
            raise HTTPException(503, 'Нет связи с Ollama. Запустите Ollama в WSL.') from error
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(502, 'Модель вернула некорректный план. Уточните запрос.') from error

def model_status():
    if config.AI_PROVIDER == 'gigachat':
        return bool(config.GIGACHAT_AUTH_KEY and config.GIGACHAT_MODEL)
    if config.AI_PROVIDER=='dashscope':return bool(config.DASHSCOPE_API_KEY and config.DASHSCOPE_MODEL)
    if config.AI_PROVIDER=='openrouter':return bool(config.OPENROUTER_API_KEY and config.OPENROUTER_MODEL)
    try:
        response = httpx.get(config.OLLAMA_BASE_URL + '/api/tags', timeout=2)
        response.raise_for_status()
        return any(item.get('name') == config.OLLAMA_MODEL for item in response.json().get('models', []))
    except (httpx.HTTPError, ValueError, TypeError):
        return False
