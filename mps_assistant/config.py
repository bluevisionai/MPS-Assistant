from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_app_service() -> bool:
    return bool(os.getenv("WEBSITE_SITE_NAME"))


def _default_data_root() -> Path:
    app_service_root = Path("/home/site")
    if _is_app_service() and app_service_root.exists():
        return app_service_root / "data"
    return Path("data")


def _default_sqlite_journal_mode() -> str:
    if _is_app_service():
        return "DELETE"
    return "WAL"


class Settings(BaseSettings):
    app_name: str = "MPS Assistant"
    seed_url: str = "https://www.medicalprotection.org/southafrica"
    allowed_domain: str = "medicalprotection.org"
    onboarding_portal_url: str = "https://mps-web-d22mja-h4awazgqdeheb8ax.z02.azurefd.net/mps/za/login"
    onboarding_auth_url: str = "https://mps-web-d22mja-h4awazgqdeheb8ax.z02.azurefd.net/api/auth/login"
    onboarding_api_base_url: str = "https://mps-api-f9e9dhhkhycnc2he.ukwest-01.azurewebsites.net/api/v1"
    onboarding_country_code: str = "za"
    onboarding_portal_username: str = ""
    onboarding_portal_password: str = ""
    onboarding_timeout_seconds: int = 20
    admin_dashboard_username: str = "admin"
    admin_dashboard_password: str = "change-me"
    admin_session_secret: str = "change-me-session-secret"
    data_dir: Path = Field(default_factory=_default_data_root)
    database_path: Path = Field(default_factory=lambda: _default_data_root() / "mps_assistant.db")
    raw_download_dir: Path = Field(default_factory=lambda: _default_data_root() / "raw")
    upload_dir: Path = Field(default_factory=lambda: _default_data_root() / "uploads")
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    openai_fallback_models: str = "gpt-5.5,gpt-5.4,gpt-5-mini,gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    refresh_interval_hours: int = 24
    refresh_timezone: str = "Africa/Johannesburg"
    refresh_hour_local: int = 0
    refresh_minute_local: int = 0
    enable_scheduler: bool = Field(default_factory=lambda: not _is_app_service())
    auto_refresh_on_startup: bool = True
    sqlite_journal_mode: str = Field(default_factory=_default_sqlite_journal_mode)
    crawl_max_pages: int = 250
    crawl_timeout_seconds: int = 20
    render_timeout_seconds: int = 35
    user_agent: str = "MPS Assistant/1.0 (+local knowledge base crawler)"
    chrome_binary_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    retrieval_top_k: int = 6
    lexical_top_k: int = 12
    semantic_top_k: int = 12
    max_chunk_chars: int = 1400
    chunk_overlap_chars: int = 250
    resource_extensions: List[str] = Field(
        default_factory=lambda: [
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".csv",
            ".txt",
            ".md",
            ".ppt",
            ".pptx",
            ".rtf",
        ]
    )
    crawl_start_urls: List[str] = Field(
        default_factory=lambda: [
            "https://www.medicalprotection.org/southafrica/join",
            "https://apply.medicalprotection.org/20",
            "https://apply.medicalprotection.org/62/student",
            "https://www.medicalprotection.org/southafrica/join/join-student-occupational-therapist/student-occupational-therapist-application",
            "https://www.medicalprotection.org/southafrica/join/state-doctor",
            "https://www.medicalprotection.org/southafrica/join/join-private-doctor",
            "https://www.medicalprotection.org/southafrica/join/community-officer",
            "https://www.medicalprotection.org/southafrica/join/join-practitioner",
            "https://www.medicalprotection.org/southafrica/join/join-occupational-therapist",
            "https://www.medicalprotection.org/southafrica/join/student",
            "https://www.medicalprotection.org/southafrica/join/join-student-occupational-therapist",
            "https://www.medicalprotection.org/southafrica/join/join-intern",
            "https://www.medicalprotection.org/southafrica/join/join-organisation",
            "https://www.medicalprotection.org/southafrica",
        ]
    )
    rendered_application_hosts: List[str] = Field(
        default_factory=lambda: [
            "apply.medicalprotection.org",
        ]
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.raw_download_dir, self.upload_dir, self.database_path.parent):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
