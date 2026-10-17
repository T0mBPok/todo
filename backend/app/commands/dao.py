from sqlalchemy import select
from app.commands.models import Command
class CommandDAO:
    def __init__(self,session): self.session=session
    def locked(self,command_id):
        return self.session.scalar(select(Command).where(Command.id==command_id).with_for_update())
