from uuid import UUID

from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure(self, user_id: UUID) -> User:
        """Idempotently create the user row."""
        user = self._session.get(User, user_id)
        if user is None:
            user = User(id=user_id)
            self._session.add(user)
            self._session.flush()
        return user
