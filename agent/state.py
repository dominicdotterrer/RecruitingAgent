from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Annotated, TypedDict


@dataclass
class JobPosting:
    id: str           # sha256[:20] of (company.lower() + title.lower() + url)
    title: str
    company: str
    url: str
    description: str
    source: str
    scraped_at: str   # ISO-8601 UTC


@dataclass
class ScoredJob:
    posting: JobPosting
    score: float
    rationale: str    # 2–3 sentences from LLM


class DailyState(TypedDict):
    sources: list[dict]
    # Annotated with operator.add so parallel scraper fan-out can merge lists
    raw_jobs: Annotated[list[JobPosting], operator.add]
    new_jobs: list[JobPosting]       # after deduplication
    filtered_jobs: list[JobPosting]  # after keyword filter
    scored_jobs: list[ScoredJob]     # after LLM ranker (score >= threshold, or top-3 fallback)
    digest_html: str
    email_sent: bool


class DiscoveryState(TypedDict):
    ambition: str
    profile: str
    serp_queries: list[str]
    candidate_urls: list[str]
    approved_sources: list[dict]
