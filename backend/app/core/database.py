from uuid import UUID

from sqlalchemy import ForeignKey, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker, with_loader_criteria
from starlette.requests import Request

from app.core.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


class Owned:
    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)


class AccountSession(Session):
    pass


@event.listens_for(AccountSession, 'do_orm_execute')
def scope_queries(query):
    if query.is_select:
        owner = query.session.info['owner_id']
        query.statement = query.statement.options(
            with_loader_criteria(Owned, lambda row: row.owner_id == owner, include_aliases=True)
        )


@event.listens_for(AccountSession, 'before_flush')
def scope_writes(session, *_):
    owner = session.info['owner_id']
    for row in session.new:
        if isinstance(row, Owned):
            row.owner_id = owner
    for row in session.dirty.union(session.deleted):
        if isinstance(row, Owned) and row.owner_id != owner:
            raise RuntimeError('Account ownership violation')


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
AccountSessionLocal = sessionmaker(engine, class_=AccountSession, expire_on_commit=False)


def get_session(request: Request):
    with AccountSessionLocal(info={'owner_id': request.state.user_id}) as session:
        yield session
