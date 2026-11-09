from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Owned


class GoogleConnection(Owned, Base):
    __tablename__ = 'google_connections'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    refresh_token: Mapped[str] = mapped_column(Text)


class GoogleState(Owned, Base):
    __tablename__ = 'google_states'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    state: Mapped[str] = mapped_column(String(64))
    session_digest: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleLink(Owned, Base):
    __tablename__ = 'google_links'
    __table_args__ = (UniqueConstraint('owner_id', 'subject', 'kind', 'remote_id'),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    local_id: Mapped[UUID] = mapped_column(primary_key=True)
    remote_id: Mapped[str] = mapped_column(String(1024))
    fingerprint: Mapped[str] = mapped_column(String(64))
    etag: Mapped[str] = mapped_column(Text)
