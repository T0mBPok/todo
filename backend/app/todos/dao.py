from sqlalchemy import select
from app.todos.models import Todo
class TodoDAO:
    def __init__(self,session):self.session=session
    def list(self):return list(self.session.scalars(select(Todo).order_by(Todo.completed,Todo.created_at.desc())))
    def get(self,id):return self.session.get(Todo,id)
    def add(self,data):
        todo=Todo(**data.model_dump());self.session.add(todo);self.session.flush();return todo
