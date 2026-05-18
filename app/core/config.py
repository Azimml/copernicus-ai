from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
INDEX_DIR = DATA_DIR / "index"
ANALYTICS_DIR = DATA_DIR / "analytics"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="local")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_base_url: str = Field(default="")

    openai_api_key: str = Field(default="")
    openai_chat_model: str = Field(default="gpt-4.1-mini")
    openai_embedding_model: str = Field(default="text-embedding-3-large")

    site_root: str = Field(default="https://copernicusberlin.org")
    crawl_paths: str = Field(default="/en")
    crawl_exclude_hosts: str = Field(default="campus.copernicusberlin.org")
    crawl_max_pages: int = Field(default=200)
    crawl_timeout_sec: float = Field(default=30.0)
    crawl_render_wait_ms: int = Field(default=2500)

    social_link_domains: str = Field(default="")

    retrieval_top_k: int = Field(default=8)
    retrieval_max_context_chars: int = Field(default=8000)
    memory_max_turns: int = Field(default=8)
    stream_chunk_chars: int = Field(default=24)

    admin_token: str = Field(default="change-me")

    # SMTP for operator replies. Leave SMTP_HOST blank to disable email
    # sending (replies will still be recorded in the handoff log).
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)
    smtp_from: str = Field(default="")
    smtp_from_name: str = Field(default="Copernicus Berlin")
    smtp_reply_to: str = Field(default="")


settings = Settings()
RAW_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)
ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
