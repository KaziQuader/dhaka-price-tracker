"""Settings read from environment variables, falling back to the `.env` file.

A real environment variable wins over `.env`. That is how the same `.env` works in two places:
inside Docker `POSTGRES_HOST=postgres` (the compose service name), and on the host the Makefile
sets `POSTGRES_HOST=localhost` for tests.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "tracker"
    postgres_password: str = "change-me"
    postgres_db: str = "tracker"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    def database_url(self, database: str | None = None) -> URL:
        """SQLAlchemy URL for psycopg 3. `database` overrides the configured DB name."""
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=database or self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
