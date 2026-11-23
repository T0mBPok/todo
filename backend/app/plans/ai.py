from app.core.ai_client import ai_post
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from app.core import config
from app.core.request_logging import log_result_rejection
from app.plans.schemas import PlanCheck, PlanOutput
from app.plans.review import build_review
from app.plans.transcript_guard import safe_transcript_edit
from app.plans.colloquial_time import resolve_colloquial_ranges
from app.tasks.schemas import TaskInput
from app.plans.dates import ANCHOR, TIME_RANGE, enforce_date_context, enforce_spoken_time, spoken_slots, words
from app.recurrences.speech import apply_spoken_recurrence
from app.plans.prompts import planning_prompt, normalize_transcript, normalization_prompt

class ExtractedPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tasks: list[TaskInput] = Field(max_length=30)
    note: str
    needs_clarification: bool
    review: list[PlanCheck] = Field(default_factory=list, max_length=30)

def parse_plan(content, spoken, timezone_name):
    value=json.loads(content)
    if isinstance(value,dict) and isinstance(value.get('tasks'),list):
        slots=list(spoken_slots(normalize_transcript(spoken)))
        for raw in value['tasks']:
            if not isinstance(raw,dict) or not isinstance(raw.get('title'),str):continue
            try:
                for field in ('start','end'):TypeAdapter(AwareDatetime).validate_python(raw.get(field))
            except ValidationError as error:
                # Repair only a fully spoken, uniquely matched interval with a
                # date. Invalid model JSON must not become an invented schedule.
                if not ANCHOR.search(spoken):continue
                tokens=set(words(raw['title']))
                scores=[len(tokens & set(words(clause))) for clause,_,_ in slots]
                best=max(scores,default=0)
                if not best or scores.count(best)!=1:continue
                clause,_,last=slots[scores.index(best)]
                if not last:continue
                now=datetime.now(ZoneInfo(timezone_name))
                candidate=TaskInput(title=raw['title'],start=now,end=now+timedelta(hours=1))
                enforce_date_context([candidate],spoken,timezone_name)
                enforce_spoken_time([candidate],clause,timezone_name)
                raw['start']=candidate.start.isoformat()
                raw['end']=candidate.end.isoformat()
                log_result_rejection('calendar_plan','recovered_datetime_field',error)
    return ExtractedPlan.model_validate(value)

class AIPlanner:
    def normalize(self, text):
        original = normalize_transcript(text)
        schema = {'type':'object', 'properties':{'text':{'type':'string'}, 'note':{'type':'string'}},
                  'required':['text','note'], 'additionalProperties':False}
        response = ai_post(config.OLLAMA_BASE_URL + '/api/chat', timeout=120, operation='transcript_normalization',
            json={'model':config.OLLAMA_MODEL, 'stream':False, 'think':False, 'keep_alive':'10m',
                  'format':schema, 'options':{'temperature':0,'num_ctx':8192,'num_predict':1800},
                  'messages':[{'role':'system','content':normalization_prompt()}, {'role':'user','content':original}]})
        response.raise_for_status()
        data = response.json()
        if data.get('done_reason') == 'length':
            log_result_rejection('transcript_normalization', 'response_truncated')
            return original, ''
        parsed = json.loads(data['message']['content'])
        if not isinstance(parsed, dict):
            raise TypeError('Expected transcript object')
        normalized = parsed.get('text')
        if not isinstance(normalized, str) or not normalized.strip() or len(normalized) > 6000:
            log_result_rejection('transcript_normalization', 'invalid_text_field')
            return original, ''
        normalized = normalize_transcript(normalized.strip())
        # Accept semantic wording repairs without enumerating every ASR typo.
        # Numeric clocks, dates and their order remain protected independently.
        if not safe_transcript_edit(original, normalized):
            log_result_rejection('transcript_normalization', 'temporal_anchors_changed')
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
        original = request._spoken_text or request.text
        time_reviews = []
        spoken = resolve_colloquial_ranges(original, request.timezone, reviews=time_reviews)
        try:
            if config.AI_PROVIDER == 'openrouter':
                normalized = normalize_transcript(spoken if spoken != original else request.text)
                instructions += '\nИсправляй очевидные оговорки при извлечении событий и сохраняй исходные даты, время и детали.'
            elif request._normalized_text is not None:
                normalized = request._normalized_text
            else:
                normalized, _ = self.normalize(spoken if spoken != original else request.text)
            planner_text = normalized + '\nИсходный текст (сохрани все детали для описания): ' + original
            if spoken != original and spoken != normalized:
                planner_text += '\nУказанное местное время: ' + spoken
            if request._normalized_text is not None and request.text not in {normalized, original}:
                planner_text += '\nУточнение из календарного контекста: ' + request.text
            response = ai_post(config.OLLAMA_BASE_URL + '/api/chat', timeout=120, operation='calendar_plan',
                json={'model': config.OLLAMA_MODEL, 'stream': False, 'think': False,
                      'keep_alive': '10m', 'format': schema,
                      'options': {'temperature': 0, 'num_ctx': 8192, 'num_predict': 4600 if len(original) > 750 else 3000},
                      'messages': [{'role': 'system', 'content': instructions},
                                   {'role': 'user', 'content': planner_text}]})
            response.raise_for_status()
            data = response.json()
            if data.get('done_reason') == 'length':
                raise HTTPException(502, 'План слишком большой. Разделите запрос на несколько частей.')
            # The accepted edit becomes the canonical wording, not a competing
            # clock source that can be overridden by broken ASR fragments.
            clock_source = normalized if safe_transcript_edit(normalize_transcript(spoken), normalized) else spoken
            clock_source = resolve_colloquial_ranges(clock_source, request.timezone)
            parsed = parse_plan(data['message']['content'], clock_source, request.timezone)
            if not parsed.tasks:
                raise HTTPException(422, parsed.note or 'Уточните день, время и задачу.')
            model_reasons = {parsed.tasks[item.task_index].title: item.reason for item in parsed.review
                             if item.task_index < len(parsed.tasks)}
            if parsed.needs_clarification and not model_reasons:
                model_reasons = {task.title: parsed.note[:500] or 'Проверьте предложенные значения.'
                                 for task in parsed.tasks}
            # Explicit descriptions survive even if transcript normalization drops them.
            detail=re.search(r'(?:в\s+описании|описание(?:\s+задачи)?|детали)\s*[:—-]\s*(.+)',request.text,re.I|re.S)
            if len(parsed.tasks)==1 and detail:
                parsed.tasks[0].description=detail.group(1).strip()[:5000]
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
            # Collapse model-expanded repetitions before matching one spoken slot
            # to one series. Otherwise duplicate titles bypass time correction.
            parsed.tasks = apply_spoken_recurrence(parsed.tasks, request.text, request.timezone)
            unresolved = enforce_spoken_time(parsed.tasks, normalize_transcript(clock_source), request.timezone)
            for index in unresolved:
                model_reasons.setdefault(parsed.tasks[index].title, 'Не удалось сверить время события с диктовкой.')
            # Linked events share a boundary after their spoken times have been applied.
            if not duration_mentioned and 'сразу' in request.text.lower():
                by_day = {}
                zone = ZoneInfo(request.timezone)
                for task in parsed.tasks:
                    by_day.setdefault(task.start.astimezone(zone).date(), []).append(task)
                for tasks in by_day.values():
                    if len(tasks) == 2:
                        first, second = sorted(tasks, key=lambda task: task.start)
                        if second.start > first.start:
                            first.end = second.start
            zone = ZoneInfo(request.timezone)
            summary = '; '.join(f'{task.title}: {task.start.astimezone(zone):%d.%m %H:%M}–{task.end.astimezone(zone):%H:%M}' for task in parsed.tasks)
            note = 'Понял: ' + summary + '.'
            if any(task.recurrence for task in parsed.tasks):
                note += ' Повторяющиеся события продолжаются без даты окончания.'
            if normalized != original:
                note += ' Нормализованный текст: ' + normalized
            if not duration_mentioned:
                note += ' Без указанной длительности — 60 минут; для связанных задач «сразу после» конец взят из начала следующей.'
            review = build_review(parsed.tasks, model_reasons, time_reviews, original, request.timezone)
            return PlanOutput(tasks=parsed.tasks, note=note, normalized_text=normalized, review=review)

        except httpx.TimeoutException as error:
            raise HTTPException(504, 'Qwen не ответила вовремя. Попробуйте ещё раз или сократите запрос.') from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                raise HTTPException(503, f'Модель {config.OLLAMA_MODEL} не найдена в Ollama.') from error
            raise HTTPException(502, 'Ошибка локальной Ollama. Проверьте её состояние.') from error
        except httpx.RequestError as error:
            raise HTTPException(503, 'Нет связи с Ollama. Запустите Ollama в WSL.') from error
        except (ValueError, KeyError, TypeError) as error:
            log_result_rejection('calendar_plan', 'invalid_schema', error)
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
