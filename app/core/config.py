from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = Field(default="Bound & Heard", validation_alias="BOUND_AND_HEARD_APP_NAME")
    admin_password: str | None = Field(
        default=None,
        validation_alias="BOUND_AND_HEARD_ADMIN_PASSWORD",
    )
    session_secret: str = Field(
        default="dev-session-secret-change-me",
        validation_alias="BOUND_AND_HEARD_SESSION_SECRET",
    )
    database_url: str = Field(
        default="sqlite:///./data/bound_and_heard.sqlite3",
        validation_alias="BOUND_AND_HEARD_DATABASE_URL",
    )
    default_user_name: str = Field(
        default="Local User",
        validation_alias="BOUND_AND_HEARD_DEFAULT_USER_NAME",
    )

    @property
    def writes_enabled(self) -> bool:
        return bool(self.admin_password and self.admin_password.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
