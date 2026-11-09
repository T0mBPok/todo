import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.core import config
from app.core.database import SessionLocal
from app.users.email_verification import code_digest, issue_challenge, rotate_code
from app.users.models import EmailChallenge, LoginSession, RateBucket, User
from app.users.schemas import ChallengeInput, CodeInput, Credentials

router = APIRouter(prefix='/auth', tags=['auth'])
passwords = PasswordHasher()
dummy_hash = passwords.hash(secrets.token_urlsafe())
COOKIE = '__Host-impulse' if config.SECURE_COOKIES else 'impulse_session'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def throttle(scope, subject, maximum, seconds):
    now = datetime.now(timezone.utc)
    window = int(now.timestamp()) // seconds
    key = digest(f'{scope}:{window}:{subject}')
    with SessionLocal.begin() as db:
        stmt = insert(RateBucket).values(key=key, count=1, expires=datetime.fromtimestamp((window + 1) * seconds, timezone.utc))
        count = db.scalar(stmt.on_conflict_do_update(index_elements=[RateBucket.key], set_={'count': RateBucket.count + 1}).returning(RateBucket.count))
        if secrets.randbelow(64) == 0:
            db.execute(delete(RateBucket).where(RateBucket.expires < now))
            db.execute(delete(LoginSession).where(LoginSession.expires < now))
    if count > maximum:
        raise HTTPException(429, 'Слишком много запросов. Попробуйте позже.')


def require_user(request: Request):
    token = request.cookies.get(COOKIE, '')
    if len(token) != 43:
        raise HTTPException(401, 'Войдите в аккаунт.')
    with SessionLocal() as db:
        user = db.scalar(select(User).join(LoginSession).where(
            LoginSession.digest == digest(token), LoginSession.expires > datetime.now(timezone.utc),
            User.email_verified_at.is_not(None)))
        if user is None:
            raise HTTPException(401, 'Войдите в аккаунт.')
        request.state.user_id = user.id
        request.state.email = user.email
    if request.method == 'POST':
        path = request.url.path
        if path.startswith(('/api/voice', '/api/commands', '/api/balance', '/api/plans', '/api/todos/commands', '/api/google/sync')):
            throttle('work', str(request.state.user_id), 20, 60)
            throttle('work-global', 'all', 60, 60)


def start_session(db, request, response, user):
    old = request.cookies.get(COOKIE, '')
    if len(old) == 43:
        db.execute(delete(LoginSession).where(LoginSession.digest == digest(old)))
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(digest=digest(token), user_id=user.id, expires=datetime.now(timezone.utc) + timedelta(days=7)))
    response.set_cookie(COOKIE, token, max_age=604800, httponly=True,
                        secure=config.SECURE_COOKIES, samesite='lax', path='/')
    return {'email': user.email}


def limit_email(address):
    throttle('email-delivery', address, 5, 3600)
    throttle('email-delivery-global', 'all', 30, 60)


@router.post('/register', status_code=202)
def register(data: Credentials, request: Request):
    throttle('register', client_ip(request), 8, 3600)
    if len(data.password) < 15:
        raise HTTPException(422, 'Пароль должен содержать минимум 15 символов.')
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == data.email)) is not None:
            raise HTTPException(409, 'Не удалось создать аккаунт. Попробуйте войти.')
    limit_email(data.email)
    return issue_challenge(data.email, password_hash=passwords.hash(data.password))


def locked_challenge(db, token, now):
    challenge = db.scalar(select(EmailChallenge).where(EmailChallenge.id == digest(token)).with_for_update())
    if challenge is None or challenge.expires <= now:
        raise HTTPException(410, 'Подтверждение истекло. Начните заново.')
    return challenge


@router.post('/resend-email', status_code=204)
def resend(data: ChallengeInput, request: Request):
    throttle('email-resend-ip', client_ip(request), 20, 900)
    with SessionLocal.begin() as db:
        challenge = locked_challenge(db, data.challenge, datetime.now(timezone.utc))
        now = datetime.now(timezone.utc)
        if challenge.resend_after > now:
            raise HTTPException(429, 'Запросить новый код можно через минуту после отправки.')
        if challenge.expires - now < timedelta(minutes=1):
            raise HTTPException(410, 'Подтверждение истекло. Начните заново.')
        limit_email(challenge.email)
        rotate_code(challenge, now)


@router.post('/verify-email')
def verify(data: CodeInput, request: Request, response: Response):
    throttle('email-verify-ip', client_ip(request), 40, 900)
    with SessionLocal.begin() as db:
        challenge = locked_challenge(db, data.challenge, datetime.now(timezone.utc))
        now = datetime.now(timezone.utc)
        if challenge.code_expires <= now or challenge.attempts_left <= 0:
            raise HTTPException(422, 'Код истёк или исчерпаны попытки. Запросите новый код.')
        if secrets.compare_digest(challenge.code_hash, code_digest(challenge.id, data.code)):
            if challenge.user_id is not None:
                user = db.scalar(select(User).where(User.id == challenge.user_id).with_for_update())
                if user is None or user.email_verified_at is not None or user.email != challenge.email:
                    raise HTTPException(409, 'Войдите в аккаунт заново.')
                user.email_verified_at = now
                db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
            else:
                user_id = db.scalar(insert(User).values(email=challenge.email, password_hash=challenge.password_hash,
                                                        email_verified_at=now)
                                    .on_conflict_do_nothing(index_elements=[User.email]).returning(User.id))
                if user_id is None:
                    raise HTTPException(409, 'Аккаунт уже создан. Войдите с паролем.')
                user = db.get(User, user_id)
            db.delete(challenge)
            return start_session(db, request, response, user)
        challenge.attempts_left -= 1
    raise HTTPException(422, 'Неверный код.')


def client_ip(request):
    # The app is published through its same-origin nginx proxy. Use the peer
    # address unless an operator explicitly configures a trusted proxy.
    if request.client and request.client.host in config.TRUSTED_PROXIES:
        return request.headers.get('x-real-ip', request.client.host)[:64]
    return request.client.host if request.client else 'unknown'


@router.post('/login')
def login(data: Credentials, request: Request, response: Response):
    throttle('login-ip', client_ip(request), 30, 900)
    throttle('login-email', data.email, 8, 900)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == data.email))
        try:
            passwords.verify(user.password_hash if user else dummy_hash, data.password)
        except VerificationError:
            raise HTTPException(401, 'Неверная почта или пароль.') from None
        if user is None:
            raise HTTPException(401, 'Неверная почта или пароль.')
        if passwords.check_needs_rehash(user.password_hash):
            user.password_hash = passwords.hash(data.password)
        if user.email_verified_at is not None:
            return start_session(db, request, response, user)
        owner_id = user.id
    limit_email(data.email)
    return issue_challenge(data.email, user_id=owner_id)


@router.get('/me')
def me(request: Request):
    require_user(request)
    return {'email': request.state.email}


@router.post('/logout', status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, '')
    if len(token) == 43:
        with SessionLocal.begin() as db:
            db.execute(delete(LoginSession).where(LoginSession.digest == digest(token)))
    response.delete_cookie(COOKIE, secure=config.SECURE_COOKIES, httponly=True, samesite='lax', path='/')
