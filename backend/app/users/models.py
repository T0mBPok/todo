from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = 'users'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailChallenge(Base):
    __tablename__ = 'email_challenges'
    __table_args__ = (
        CheckConstraint('(user_id IS NULL) <> (password_hash IS NULL)', name='email_challenge_purpose'),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    code_expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resend_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts_left: Mapped[int]


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RateBucket(Base):
    __tablename__ = 'rate_buckets'
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int]
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
