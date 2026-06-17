import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import User


logger = logging.getLogger(__name__)

DEFAULT_LOCAL_USER_ID = 1


def ensure_default_user(db: Session, display_name: str) -> User:
    user = db.get(User, DEFAULT_LOCAL_USER_ID)
    if user is not None:
        return user

    existing_user = db.scalars(select(User).limit(1)).first()
    if existing_user is not None:
        return existing_user

    user = User(id=DEFAULT_LOCAL_USER_ID, display_name=display_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def bootstrap_default_user(display_name: str) -> None:
    try:
        with SessionLocal() as db:
            ensure_default_user(db, display_name)
    except SQLAlchemyError:
        logger.exception("Failed to bootstrap default local user. Have migrations been run?")
        raise
