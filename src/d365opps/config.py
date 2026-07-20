from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="D365_OPPS_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    database_url: str = "sqlite:///./var/d365opps.db"
    blob_root: Path = Path("./var/blob")
    export_root: Path = Path("./var/exports")
    log_root: Path = Path("./var/logs")
    artifact_root: Path = Path("./artifacts")
    web_base_url: str | None = None
    http_timeout_seconds: int = 30
    fetch_window_days: int = 7
    incremental_window_days: int = Field(default=7, ge=1, le=90)
    backfill_window_days: int = Field(default=90, ge=7, le=3650)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 "
        "d365-opportunity-engine/0.1"
    )
    sam_gov_api_key: str | None = None
    search_api_endpoint: str | None = None
    search_api_key: str | None = None
    gleif_enabled: bool = True
    ted_scope: str = "ALL"
    ted_limit: int = Field(default=100, ge=1, le=250)
    contracts_finder_limit: int = Field(default=100, ge=1, le=500)
    max_pages_per_run: int = Field(default=25, ge=1, le=500)
    incremental_max_pages_per_source: int = Field(default=25, ge=1, le=500)
    backfill_max_pages_per_source: int = Field(default=120, ge=1, le=5000)
    incremental_max_notices_per_source: int = Field(default=500, ge=1, le=10000)
    backfill_max_notices_per_source: int = Field(default=5000, ge=1, le=50000)
    max_detail_pages_per_source: int = Field(default=80, ge=0, le=5000)
    max_attachments_per_source: int = Field(default=120, ge=0, le=5000)
    max_runtime_seconds_per_source: int = Field(default=900, ge=30, le=14400)
    query_fanout_limit: int = Field(default=12, ge=1, le=100)
    backfill_query_fanout_limit: int = Field(default=24, ge=1, le=200)
    retrieval_min_score: int = Field(default=40, ge=0, le=100)
    signal_min_score: int = Field(default=22, ge=0, le=100)
    attachment_fetch_enabled: bool = True
    max_attachment_fetch_per_record: int = Field(default=2, ge=0, le=10)
    max_attachment_bytes: int = Field(default=5242880, ge=1024, le=52428800)
    source_discovery_limit: int = Field(default=100, ge=1, le=1000)
    potential_hits_limit: int = Field(default=12, ge=1, le=100)
    potential_hits_ai_shortlist: int = Field(default=24, ge=1, le=200)
    potential_hits_ai_enabled: bool = True
    detail_follow_candidate_limit: int = Field(default=250, ge=1, le=2000)
    detail_follow_per_candidate_limit: int = Field(default=5, ge=1, le=25)
    detail_follow_concurrency: int = Field(default=8, ge=1, le=64)
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_review_model: str = "gpt-5.4-mini"
    forensic_log_retention_days: int = Field(default=14, ge=1, le=365)
    verification_sample_limit: int = Field(default=100, ge=10, le=5000)
    screenshot_capture_enabled: bool = False
    demo_mode: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.blob_root.mkdir(parents=True, exist_ok=True)
    settings.export_root.mkdir(parents=True, exist_ok=True)
    settings.log_root.mkdir(parents=True, exist_ok=True)
    settings.artifact_root.mkdir(parents=True, exist_ok=True)
    Path("./var").mkdir(exist_ok=True)
    return settings
