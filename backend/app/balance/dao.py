from sqlalchemy import select
from app.commands.models import Command
class BalanceDAO:
    def __init__(self,session):self.session=session
    def get(self,id):return self.session.scalar(select(Command).where(Command.id==id).with_for_update())
    def add(self,operations,note):
        command=Command(text='Балансировка нагрузки',operations=operations,note=note,status='draft')
        self.session.add(command);self.session.commit();return command
