"""Run only as an operator, after checking who owns the pre-account data."""
import argparse

from sqlalchemy import select, update

from app.commands.models import Command
from app.core.database import SessionLocal
from app.plans.models import Plan
from app.tasks.models import Task
from app.todos.models import Todo
from app.users.models import User


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('email')
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        owner = db.scalar(select(User.id).where(User.email == args.email.strip().casefold()))
        if owner is None:
            parser.error('Зарегистрируйте этот аккаунт перед переносом.')
        for model in (Plan, Task, Todo, Command):
            result = db.execute(update(model).where(model.owner_id.is_(None)).values(owner_id=owner))
            print(f'{model.__tablename__}: {result.rowcount}')


if __name__ == '__main__':
    main()
