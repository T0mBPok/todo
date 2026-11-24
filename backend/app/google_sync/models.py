from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, Owned


class GoogleConnection(Owned, Base):
    __tablename__ = 'google_connections'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255))
    refresh_token: Mapped[str] = mapped_column(Text)
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(Text)
    sync_conflicts: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    sync_partial: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class GoogleState(Owned, Base):
    __tablename__ = 'google_states'
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    state: Mapped[str] = mapped_column(String(64))
    session_digest: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleLink(Owned, Base):
    __tablename__ = 'google_links'
    __table_args__ = (UniqueConstraint('owner_id', 'subject', 'kind', 'task_list_id', 'remote_id', name='uq_google_links_remote_list'),)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    local_id: Mapped[UUID] = mapped_column(primary_key=True)
    task_list_id: Mapped[str] = mapped_column(String(1024), default='@default', server_default='@default')
    remote_id: Mapped[str] = mapped_column(String(1024))
    fingerprint: Mapped[str] = mapped_column(String(64))
    etag: Mapped[str] = mapped_column(Text)
    export_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conflict: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
