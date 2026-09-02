"""On-demand FastAPI job alerts backed by the JSearch RapidAPI API."""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from config import AppConfig, load_config
from constants import (
    ALLOWED_CITIES,
    ALLOWED_ROLE_PHRASES,
    JSEARCH_HOST,
    JSEARCH_RESULTS_PER_PAGE,
    JSEARCH_URL,
    MAX_PAGES_PER_FETCH,
    MAX_RESULTS_PER_FETCH,
    MAX_JOB_AGE,
    SEARCH_PARAMS,
)


DatePosted = Literal["today", "3days", "week", "month"]


class JobAlert(BaseModel):
    """The intentionally small job shape exposed by this service."""

    model_config = ConfigDict(extra="ignore")

    job_id: str
    employer_name: str | None = None
    job_title: str
    job_apply_link: str | None = None


class JobHistoryEntry(JobAlert):
    """A job retained for display in the previously fetched list."""

    fetched_at: datetime


# Coordinates reads and atomic rewrites in the documented single-worker setup.
_jobs_file_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Prune expired persisted jobs once whenever the application starts."""

    config = load_config()
    async with _jobs_file_lock:
        _ensure_seen_jobs_file(config.seen_jobs_file)
        _prune_stale_persisted_jobs(config, datetime.now(timezone.utc))
    yield


app = FastAPI(
    title="Personal Job Alert System",
    description="Fetches fresh Bangalore job matches from JSearch v5 on demand.",
    version="1.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _normalize_words(value: str) -> str:
    """Make punctuation and casing differences comparable."""

    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _clean_filter_values(values: list[str] | None, defaults: tuple[str, ...]) -> tuple[str, ...]:
    candidates = values if values is not None else list(defaults)
    return tuple(dict.fromkeys(value.strip() for value in candidates if value.strip()))


def _title_is_allowed(title: Any, allowed_role_phrases: tuple[str, ...]) -> bool:
    if not isinstance(title, str) or not title.strip():
        return False
    normalized_title = _normalize_words(title)
    return any(
        _normalize_words(role) in normalized_title
        for role in allowed_role_phrases
    )


def _city_is_allowed(city: Any, allowed_cities: frozenset[str]) -> bool:
    return isinstance(city, str) and city.strip().casefold() in allowed_cities


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_fresh(posted_at: Any, now: datetime) -> bool:
    posted_datetime = _parse_utc_datetime(posted_at)
    return posted_datetime is not None and now - posted_datetime <= MAX_JOB_AGE


def _read_seen_jobs(seen_jobs_file: Path) -> dict[str, datetime]:
    """Read `job_id<TAB>fetched_at` entries, ignoring malformed legacy rows."""

    try:
        with seen_jobs_file.open("r", encoding="utf-8") as file:
            lines = file.readlines()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the local seen-jobs file.",
        ) from exc

    entries: dict[str, datetime] = {}
    for line in lines:
        parts = line.rstrip("\r\n").split("\t", maxsplit=1)
        if len(parts) != 2:
            continue
        job_id, fetched_at_text = parts
        fetched_at = _parse_utc_datetime(fetched_at_text)
        if job_id and fetched_at is not None:
            entries[job_id] = fetched_at
    return entries


def _ensure_seen_jobs_file(seen_jobs_file: Path) -> None:
    """Create the ignored runtime deduplication file when it is absent."""

    try:
        seen_jobs_file.parent.mkdir(parents=True, exist_ok=True)
        seen_jobs_file.touch(exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not create the local seen-jobs file.",
        ) from exc


def _write_seen_jobs(entries: dict[str, datetime], seen_jobs_file: Path) -> None:
    temporary_file = seen_jobs_file.with_suffix(".txt.tmp")
    try:
        seen_jobs_file.parent.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding="utf-8", newline="\n") as file:
            for job_id, fetched_at in entries.items():
                file.write(f"{job_id}\t{fetched_at.isoformat()}\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_file.replace(seen_jobs_file)
    except OSError as exc:
        try:
            temporary_file.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail="Could not update the local seen-jobs file.",
        ) from exc


def _read_job_history(job_history_file: Path) -> list[JobHistoryEntry]:
    try:
        with job_history_file.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not read the local job-history file.",
        ) from exc

    if not isinstance(payload, list):
        raise HTTPException(
            status_code=500,
            detail="The local job-history file has an invalid format.",
        )

    try:
        return [JobHistoryEntry.model_validate(item) for item in payload]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail="The local job-history file contains invalid job data.",
        ) from exc


def _write_job_history(
    history: list[JobHistoryEntry],
    job_history_file: Path,
) -> None:
    temporary_file = job_history_file.with_suffix(".json.tmp")
    try:
        job_history_file.parent.mkdir(parents=True, exist_ok=True)
        with temporary_file.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(
                [entry.model_dump(mode="json") for entry in history],
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temporary_file.replace(job_history_file)
    except OSError as exc:
        try:
            temporary_file.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=500,
            detail="Could not update the local job-history file.",
        ) from exc


def _prune_stale_persisted_jobs(config: AppConfig, now: datetime) -> None:
    """Remove records fetched more than 30 days ago from both local stores."""

    cutoff = now - MAX_JOB_AGE
    history = _read_job_history(config.job_history_file)
    fresh_history = [entry for entry in history if entry.fetched_at >= cutoff]

    seen_jobs = {
        job_id: fetched_at
        for job_id, fetched_at in _read_seen_jobs(config.seen_jobs_file).items()
        if fetched_at >= cutoff
    }

    # History can repair a missing dedup row after an interrupted prior write.
    for entry in fresh_history:
        seen_jobs.setdefault(entry.job_id, entry.fetched_at)

    _write_job_history(fresh_history, config.job_history_file)
    _write_seen_jobs(seen_jobs, config.seen_jobs_file)


async def _fetch_jsearch_page(
    config: AppConfig,
    search_params: dict[str, str],
) -> tuple[list[dict[str, Any]], str | None]:
    headers = {
        "X-RapidAPI-Key": config.rapidapi_key,
        "X-RapidAPI-Host": JSEARCH_HOST,
    }
    timeout = httpx.Timeout(
        config.request_timeout_seconds,
        connect=config.connect_timeout_seconds,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                JSEARCH_URL,
                headers=headers,
                params=search_params,
            )
            response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="JSearch request timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"JSearch returned HTTP {exc.response.status_code}.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach JSearch.") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="JSearch returned invalid JSON.") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    jobs = data.get("jobs") if isinstance(data, dict) else data
    cursor_value = data.get("cursor") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise HTTPException(status_code=502, detail="JSearch returned an unexpected response.")
    cursor = cursor_value if isinstance(cursor_value, str) and cursor_value else None
    return [job for job in jobs if isinstance(job, dict)], cursor


async def _fetch_jsearch_jobs(
    config: AppConfig,
    search_params: dict[str, str],
    max_results: int,
) -> list[dict[str, Any]]:
    """Follow bounded v5 cursors without exceeding the per-click result cap."""

    jobs: list[dict[str, Any]] = []
    cursor: str | None = None
    used_cursors: set[str] = set()
    max_pages = min(
        MAX_PAGES_PER_FETCH,
        (max_results + JSEARCH_RESULTS_PER_PAGE - 1) // JSEARCH_RESULTS_PER_PAGE,
    )

    for _ in range(max_pages):
        page_params = dict(search_params)
        if cursor:
            page_params["cursor"] = cursor

        page_jobs, next_cursor = await _fetch_jsearch_page(config, page_params)
        jobs.extend(page_jobs)

        if len(jobs) >= max_results or not next_cursor or next_cursor in used_cursors:
            break
        used_cursors.add(next_cursor)
        cursor = next_cursor

    return jobs[:max_results]


@app.get("/jobs/history", response_model=list[JobHistoryEntry])
async def get_job_history() -> list[JobHistoryEntry]:
    """Return retained fetched jobs, newest first."""

    config = load_config()
    async with _jobs_file_lock:
        _ensure_seen_jobs_file(config.seen_jobs_file)
        history = _read_job_history(config.job_history_file)
    return list(reversed(history))


@app.get("/fetch-jobs", response_model=list[JobHistoryEntry])
async def fetch_jobs(
    query: Annotated[str, Query(min_length=2, max_length=200)] = SEARCH_PARAMS["query"],
    country: Annotated[str, Query(pattern=r"^[A-Za-z]{2}$")] = SEARCH_PARAMS["country"],
    language: Annotated[str, Query(pattern=r"^[A-Za-z]{2}$")] = SEARCH_PARAMS["language"],
    date_posted: DatePosted = SEARCH_PARAMS["date_posted"],
    max_results: Annotated[int, Query(ge=1, le=MAX_RESULTS_PER_FETCH)] = MAX_RESULTS_PER_FETCH,
    city: Annotated[list[str] | None, Query(max_length=80)] = None,
    role: Annotated[list[str] | None, Query(max_length=100)] = None,
) -> list[JobHistoryEntry]:
    """Fetch, filter, timestamp, deduplicate, persist, and return new jobs."""

    config = load_config()
    async with _jobs_file_lock:
        _ensure_seen_jobs_file(config.seen_jobs_file)

    if not config.has_rapidapi_key:
        raise HTTPException(
            status_code=503,
            detail="Add RAPIDAPI_KEY to the .env file before fetching jobs.",
        )

    allowed_city_values = _clean_filter_values(city, tuple(ALLOWED_CITIES))
    allowed_role_phrases = _clean_filter_values(role, ALLOWED_ROLE_PHRASES)
    allowed_cities = frozenset(value.casefold() for value in allowed_city_values)
    if not allowed_cities or not allowed_role_phrases:
        raise HTTPException(
            status_code=422,
            detail="At least one allowed city and role phrase is required.",
        )

    search_params = {
        "query": query.strip(),
        "country": country.casefold(),
        "language": language.casefold(),
        "date_posted": date_posted,
    }
    incoming_jobs = await _fetch_jsearch_jobs(config, search_params, max_results)
    fetched_at = datetime.now(timezone.utc)

    async with _jobs_file_lock:
        seen_jobs = _read_seen_jobs(config.seen_jobs_file)
        history = _read_job_history(config.job_history_file)
        new_jobs: list[JobHistoryEntry] = []

        for job in incoming_jobs:
            raw_job_id = job.get("job_id")
            job_id = raw_job_id.strip() if isinstance(raw_job_id, str) else ""

            if (
                not job_id
                or any(character in job_id for character in "\r\n\t")
                or job_id in seen_jobs
                or not _city_is_allowed(job.get("job_city"), allowed_cities)
                or not _is_fresh(job.get("job_posted_at_datetime_utc"), fetched_at)
                or not _title_is_allowed(job.get("job_title"), allowed_role_phrases)
            ):
                continue

            entry = JobHistoryEntry(
                job_id=job_id,
                employer_name=job.get("employer_name"),
                job_title=job["job_title"].strip(),
                job_apply_link=job.get("job_apply_link"),
                fetched_at=fetched_at,
            )
            new_jobs.append(entry)
            seen_jobs[job_id] = fetched_at

        if new_jobs:
            history.extend(new_jobs)
            _write_job_history(history, config.job_history_file)
            _write_seen_jobs(seen_jobs, config.seen_jobs_file)

    return new_jobs
