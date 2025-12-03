from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения и файла `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_dsn: str = "postgresql://github_top:github_top@localhost:5432/github_top"
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10

    github_token: SecretStr | None = None
    github_api_url: str = "https://api.github.com"
    github_top_limit: int = 100
    github_max_concurrent_requests: int = 5
    github_max_rps: float = 10.0
    github_max_commit_pages: int = 10

    clickhouse_url: str = "http://localhost:8123"
    clickhouse_user: str = "default"
    clickhouse_password: SecretStr = SecretStr("")
    clickhouse_database: str = "test"
    clickhouse_batch_size: int = 1000
