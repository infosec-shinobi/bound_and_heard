from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import bootstrap
from app.core.bootstrap import DEFAULT_LOCAL_USER_ID, bootstrap_default_user, ensure_default_user
from app.core.config import Settings
from app.core.database import Base
from app.models import User


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_settings_disable_writes_when_admin_password_is_missing() -> None:
    settings = Settings(admin_password=None)

    assert settings.writes_enabled is False


def test_settings_disable_writes_when_admin_password_is_blank() -> None:
    settings = Settings(admin_password="   ")

    assert settings.writes_enabled is False


def test_settings_enable_writes_when_admin_password_is_set() -> None:
    settings = Settings(admin_password="secret")

    assert settings.writes_enabled is True


def test_ensure_default_user_creates_default_local_user() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        user = ensure_default_user(db, "Local Reader")

        assert user.id == DEFAULT_LOCAL_USER_ID
        assert user.display_name == "Local Reader"


def test_ensure_default_user_returns_existing_user_without_overwriting_name() -> None:
    session_factory = make_session_factory()

    with session_factory() as db:
        db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Existing User"))
        db.commit()

        user = ensure_default_user(db, "New Name")

        assert user.id == DEFAULT_LOCAL_USER_ID
        assert user.display_name == "Existing User"


def test_bootstrap_default_user_uses_configured_session_factory(monkeypatch) -> None:
    session_factory = make_session_factory()
    monkeypatch.setattr(bootstrap, "SessionLocal", session_factory)

    bootstrap_default_user("Bootstrapped User")

    with session_factory() as db:
        user = db.scalars(select(User)).one()

    assert user.id == DEFAULT_LOCAL_USER_ID
    assert user.display_name == "Bootstrapped User"
