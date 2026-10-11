from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository


def ensure_user(session: Session, user_id: UUID) -> None:
    """Idempotently seed the single user row."""
    UserRepository(session).ensure(user_id)
