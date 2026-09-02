"""Environment-driven runtime configuration for the job alert service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


RAPIDAPI_KEY_PLACEHOLDER = "YOUR_RAPIDAPI_KEY_HERE"
DEFAULT_ENV_FILE = Path(__file__).resolve().with_name(".env")
DEFAULT_SEEN_JOBS_FILE = Path(__file__).resolve().with_name(
    "applied_or_seen_jobs.txt"
)
DEFAULT_JOB_HISTORY_FILE = Path(__file__).resolve().with_name("job_history.json")


@dataclass(frozen=True, slots=True)
class AppConfig:
    rapidapi_key: str
    seen_jobs_file: Path = DEFAULT_SEEN_JOBS_FILE
    job_history_file: Path = DEFAULT_JOB_HISTORY_FILE
    request_timeout_seconds: float = 20.0
    connect_timeout_seconds: float = 10.0

    @property
    def has_rapidapi_key(self) -> bool:
        return bool(
            self.rapidapi_key
            and self.rapidapi_key != RAPIDAPI_KEY_PLACEHOLDER
        )


def load_config() -> AppConfig:
    """Load runtime values so environment changes are picked up per request."""

    file_values = dotenv_values(DEFAULT_ENV_FILE)
    api_key = os.getenv("RAPIDAPI_KEY") or file_values.get("RAPIDAPI_KEY")
    return AppConfig(
        rapidapi_key=(api_key or RAPIDAPI_KEY_PLACEHOLDER).strip()
    )
