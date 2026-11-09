import hashlib
import hmac
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import HTTPException
from sqlalchemy import delete

from app.core import config
from app.core.database import SessionLocal
from app.users.models import EmailChallenge


def code_digest(challenge_id, code):
    key = config.EMAIL_CODE_KEY.encode()
    if len(key) < 32:
        raise HTTPException(503, 'Подтверждение почты ещё не настроено.')
    return hmac.new(key, f'{challenge_id}:{code}'.encode(), hashlib.sha256).hexdigest()


def send_code(address, code):
    if not config.SMTP_HOST or not config.SMTP_FROM:
        raise HTTPException(503, 'Отправка кодов ещё не настроена.')
    message = EmailMessage()
    message['From'] = config.SMTP_FROM
    message['To'] = address
    message['Subject'] = 'Импульс — код подтверждения почты'
    message.set_content(f'Код подтверждения: {code}\n\nКод действует 10 минут. Если вы не запрашивали код, проигнорируйте письмо.')
    context = ssl.create_default_context()
    try:
        if config.SMTP_TLS == 'implicit':
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=8, context=context)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=8)
        with server:
            if config.SMTP_TLS == 'starttls':
                server.starttls(context=context)
            if config.SMTP_USERNAME:
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(message)
    except (smtplib.SMTPException, OSError, UnicodeError):
        raise HTTPException(502, 'Не удалось отправить письмо. Попробуйте позже.') from None


def rotate_code(challenge, now):
    code = f'{secrets.randbelow(10**8):08d}'
    challenge.code_hash = code_digest(challenge.id, code)
    challenge.code_expires = min(now + timedelta(minutes=10), challenge.expires)
    challenge.resend_after = now + timedelta(seconds=60)
    challenge.attempts_left = 5
    send_code(challenge.email, code)


def issue_challenge(email, password_hash=None, user_id=None):
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    challenge = EmailChallenge(
        id=hashlib.sha256(token.encode()).hexdigest(), email=email, password_hash=password_hash,
        user_id=user_id, expires=now + timedelta(minutes=30),
    )
    with SessionLocal.begin() as db:
        db.execute(delete(EmailChallenge).where(EmailChallenge.expires < now))
        rotate_code(challenge, now)
        db.add(challenge)
    return {'email': email, 'challenge': token}
