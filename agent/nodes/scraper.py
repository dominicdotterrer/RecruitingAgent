"""
Scraper node: loads sources.yaml and fetches job postings from all sources.

Scraper strategies keyed by source type:
  - careers_page  : direct LLM extraction from the careers URL
  - job_board     : board-specific search URL construction + LLM extraction
  - vc_portfolio  : two-step (portfolio companies → each company's careers page)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import re

import anthropic
import httpx
import yaml

from agent.state import DailyState, JobPosting
from agent.tools.scrape_tool import fetch_page_content

CONFIG_DIR = Path("config")

# Search terms used when scraping generic job boards
INDEED_SEARCH_TERMS = [
    "research scientist defense autonomy",
    "principal scientist physical AI",
    "applied mathematician machine learning",
    "R&D scientist autonomous systems",
    "quantitative researcher hard tech",
]

CAREERS_PATHS = [
    "/careers",
    "/jobs",
    "/open-roles",
    "/about/careers",
    "/company/careers",
    "/work-with-us",
    "/join-us",
]

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _job_id(company: str, title: str, url: str) -> str:
    raw = f"{company.lower().strip()}{title.lower().strip()}{url.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _parse_json_response(text: str) -> list[dict]:
    """Extract and parse the first JSON array from an LLM response.

    Handles markdown fences, trailing explanation text, and extra newlines
    that cause json.loads to raise 'Extra data'.
    """
    text = text.strip()
    # Unwrap markdown code fence if present
    fence_match = re.search(r"```(?:\w+)?\n([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    # Extract the first [...] block, including nested structures
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        text = arr_match.group(0)
    return json.loads(text)


async def _extract_jobs_llm(markdown: str, source_name: str, source_url: str) -> list[JobPosting]:
    """Use Haiku to extract structured job listings from scraped markdown."""
    if not markdown or len(markdown.strip()) < 100:
        return []

    prompt = f"""Extract all job listings from this page content.
Source: {source_name} ({source_url})

--- PAGE CONTENT ---
{markdown[:5000]}
--- END ---

Return a JSON array. Each element must have these keys:
  "title"       : job title (string)
  "company"     : company name (string)
  "url"         : direct URL to the job posting or application page (string; use source URL if unknown)
  "description" : role description or requirements, max 400 characters (string)

Return ONLY the JSON array. If no jobs are found, return []."""

    msg = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        jobs_data = _parse_json_response(msg.content[0].text)
    except (json.JSONDecodeError, IndexError) as e:
        raw = msg.content[0].text[:400] if msg.content else "(empty)"
        print(f"LLM extraction parse error for {source_url}: {e}\n  Raw response: {raw!r}")
        return []

    now = datetime.now(timezone.utc).isoformat()
    results = []
    for j in jobs_data:
        title = j.get("title", "").strip()
        company = j.get("company", source_name).strip()
        url = j.get("url", source_url).strip()
        if not title:
            continue
        results.append(
            JobPosting(
                id=_job_id(company, title, url),
                title=title,
                company=company,
                url=url,
                description=j.get("description", "")[:400],
                source=source_name,
                scraped_at=now,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Strategy: careers_page
# ---------------------------------------------------------------------------

async def _scrape_careers_page(source: dict) -> list[JobPosting]:
    url = source["url"]
    company = source.get("company", urlparse(url).netloc)
    content = await fetch_page_content(url)
    return await _extract_jobs_llm(content, company, url)


# ---------------------------------------------------------------------------
# Strategy: job_board
# ---------------------------------------------------------------------------

async def _scrape_job_board(source: dict) -> list[JobPosting]:
    scraper = source.get("scraper", "")
    all_jobs: list[JobPosting] = []

    if scraper == "indeed":
        for term in INDEED_SEARCH_TERMS:
            url = f"https://www.indeed.com/jobs?q={term.replace(' ', '+')}&sort=date&fromage=1"
            content = await fetch_page_content(url)
            jobs = await _extract_jobs_llm(content, f"Indeed", url)
            all_jobs.extend(jobs)
            await asyncio.sleep(random.uniform(2.0, 4.0))

    elif scraper == "mathjobs":
        content = await fetch_page_content(source["url"])
        all_jobs.extend(await _extract_jobs_llm(content, "MathJobs", source["url"]))

    elif scraper == "usajobs":
        url = (
            "https://www.usajobs.gov/Search/Results"
            "?k=mathematician+data+scientist+research+autonomy&p=1"
        )
        content = await fetch_page_content(url)
        all_jobs.extend(await _extract_jobs_llm(content, "USAJobs", url))

    else:
        content = await fetch_page_content(source["url"])
        all_jobs.extend(await _extract_jobs_llm(content, source["url"], source["url"]))

    return all_jobs


# ---------------------------------------------------------------------------
# Strategy: vc_portfolio
# ---------------------------------------------------------------------------

async def _find_careers_url(company_url: str) -> str | None:
    """Try common careers paths to find a valid careers page."""
    base = company_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for path in CAREERS_PATHS:
            url = base + path
            try:
                resp = await client.head(url)
                if resp.status_code < 400:
                    return url
            except Exception:
                continue
    return None


async def _scrape_vc_portfolio(source: dict) -> list[JobPosting]:
    portfolio_url = source["portfolio_url"]
    name = source.get("name", urlparse(portfolio_url).netloc)
    filter_keyword = source.get("filter", "").lower()

    # Step 1: extract portfolio company list
    content = await fetch_page_content(portfolio_url)
    if not content:
        return []

    prompt = f"""Extract all portfolio company names and their website URLs from this VC portfolio page.

{content[:4000]}

Return a JSON array: [{{"name": "Company Name", "url": "https://company.com"}}]
Return ONLY the JSON array."""

    msg = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        companies = _parse_json_response(msg.content[0].text)
    except (json.JSONDecodeError, IndexError) as e:
        raw = msg.content[0].text[:400] if msg.content else "(empty)"
        print(f"Portfolio extraction failed for {portfolio_url}: {e}\n  Raw response: {raw!r}")
        return []

    # Step 2: scrape each company's careers page
    all_jobs: list[JobPosting] = []
    for company in companies[:20]:
        company_name = company.get("name", "").strip()
        company_url = company.get("url", "").strip()
        if not company_url:
            continue
        if filter_keyword and filter_keyword not in company_name.lower():
            continue

        careers_url = await _find_careers_url(company_url)
        if not careers_url:
            continue

        content = await fetch_page_content(careers_url)
        jobs = await _extract_jobs_llm(content, f"{company_name} (via {name})", careers_url)
        all_jobs.extend(jobs)
        await asyncio.sleep(random.uniform(1.0, 3.0))

    return all_jobs


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

def load_sources(state: DailyState) -> dict:
    with open(CONFIG_DIR / "sources.yaml") as f:
        data = yaml.safe_load(f)
    sources = []
    for entries in data.values():
        if isinstance(entries, list):
            sources.extend(entries)
    print(f"Loaded {len(sources)} sources")
    return {"sources": sources}


async def _scrape_source_safe(source: dict) -> list[JobPosting]:
    try:
        source_type = source.get("type")
        if source_type == "careers_page":
            return await _scrape_careers_page(source)
        elif source_type == "job_board":
            return await _scrape_job_board(source)
        elif source_type == "vc_portfolio":
            return await _scrape_vc_portfolio(source)
        return []
    except Exception as e:
        import traceback
        label = source.get("url") or source.get("portfolio_url") or "unknown"
        print(f"Scraper error [{label}]: {type(e).__name__}: {e}")
        print(traceback.format_exc())
        return []


def scrape_sources(state: DailyState) -> dict:
    async def run_all():
        tasks = [_scrape_source_safe(s) for s in state["sources"]]
        results = await asyncio.gather(*tasks)
        return [job for batch in results for job in batch]

    jobs = asyncio.run(run_all())
    print(f"Scraped {len(jobs)} raw job postings across all sources")
    return {"raw_jobs": jobs}
