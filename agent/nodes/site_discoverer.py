"""
Weekly site-discovery agent.

Generates SERP queries from ambition.md, runs them via Brave Search,
scores each new domain with an LLM, and appends approved sources to
sources.yaml with a git commit.
"""
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import yaml

from agent.state import DailyState, DiscoveryState
from agent.tools.serp_tool import brave_search


def _parse_json_response(text: str) -> list[dict]:
    text = text.strip()
    fence_match = re.search(r"```(?:\w+)?\n([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()
    arr_match = re.search(r"\[[\s\S]*\]", text)
    if arr_match:
        text = arr_match.group(0)
    return json.loads(text)

CONFIG_DIR = Path("config")


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def load_config(state: DiscoveryState) -> dict:
    with open(CONFIG_DIR / "ambition.md") as f:
        ambition = f.read()
    with open(CONFIG_DIR / "profile.md") as f:
        profile = f.read()
    return {"ambition": ambition, "profile": profile}


def generate_queries(state: DiscoveryState) -> dict:
    prompt = f"""Based on this statement of ambition, generate 12 SERP search queries to find relevant job postings, career pages, and job boards.

{state['ambition']}

Target:
- Research scientist / principal scientist roles in physical AI, defense tech, robotics, autonomous systems, geospatial/ISR
- Niche job boards for math, hard science, or defense-adjacent tech
- Company careers pages in the defense/autonomy/physical AI space
- VC portfolio pages with a defense or hard-science focus

Return exactly 12 queries, one per line. No numbering, no bullets, no extra text."""

    msg = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    queries = [
        line.strip()
        for line in msg.content[0].text.strip().split("\n")
        if line.strip()
    ][:12]
    print(f"Generated {len(queries)} SERP queries")
    return {"serp_queries": queries}


def run_serp(state: DiscoveryState) -> dict:
    """Execute all queries; collect one representative URL per unique domain."""
    domain_to_url: dict[str, str] = {}
    for query in state["serp_queries"]:
        try:
            results = brave_search(query, count=10)
        except Exception as e:
            print(f"SERP error for '{query}': {e}")
            continue
        for r in results:
            domain = urlparse(r["url"]).netloc
            if domain and domain not in domain_to_url:
                domain_to_url[domain] = r["url"]

    candidate_urls = list(domain_to_url.values())
    print(f"SERP run: {len(candidate_urls)} unique domains from {len(state['serp_queries'])} queries")
    return {"candidate_urls": candidate_urls}


def _load_existing_domains() -> set[str]:
    with open(CONFIG_DIR / "sources.yaml") as f:
        existing = yaml.safe_load(f)
    domains: set[str] = set()
    for entries in existing.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for key in ("url", "portfolio_url"):
                if key in entry:
                    domains.add(urlparse(entry[key]).netloc)
    return domains


def _write_and_commit_sources(approved: list[dict], commit_msg: str) -> None:
    sources_path = CONFIG_DIR / "sources.yaml"
    with open(sources_path) as f:
        sources = yaml.safe_load(f)

    type_to_category = {
        "job_board": "job_boards",
        "careers_page": "company_careers",
        "vc_portfolio": "vc_portfolios",
    }
    for source in approved:
        site_type = source.pop("type")
        category = type_to_category.get(site_type, "job_boards")
        sources.setdefault(category, []).append(source)

    with open(sources_path, "w") as f:
        yaml.dump(sources, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # Ensure git identity is set regardless of workflow environment
    subprocess.run(["git", "config", "user.name", "job-search-agent[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "job-search-agent[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", str(sources_path)], check=True)
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "push"], check=True)
    print(f"Committed and pushed {len(approved)} new source(s) to sources.yaml")


def _score_candidate_urls(candidate_urls: list[str], existing_domains: set[str]) -> list[dict]:
    """Score a list of candidate URLs; return approved source dicts."""
    new_candidates = [u for u in candidate_urls if urlparse(u).netloc not in existing_domains][:50]
    if not new_candidates:
        print("No new candidate domains to evaluate")
        return []

    url_list = "\n".join(f"- {u}" for u in new_candidates)
    prompt = f"""Classify each URL below as one of: job_board, careers_page, vc_portfolio, or irrelevant.

Context — I'm looking for sources relevant to:
defense tech, physical AI, robotics, autonomous systems, geospatial/ISR, hard science R&D, and quantitative research.

URLs:
{url_list}

For each URL that is NOT irrelevant, return a line in exactly this pipe-delimited format:
<url> | <type> | <one-sentence reason>

Omit irrelevant URLs entirely. Use only the types: job_board, careers_page, vc_portfolio."""

    msg = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    approved: list[dict] = []
    today = str(date.today())
    valid_types = {"job_board", "careers_page", "vc_portfolio"}

    for line in msg.content[0].text.strip().split("\n"):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        url = parts[0]
        site_type = parts[1].lower().replace(" ", "_")
        reason = parts[2] if len(parts) > 2 else ""
        domain = urlparse(url).netloc
        if site_type in valid_types and domain and domain not in existing_domains:
            approved.append(
                {"url": url, "type": site_type, "discovered_date": today, "discovery_reason": reason}
            )

    print(f"Site scorer: {len(approved)} new source(s) approved")
    return approved


def score_sites(state: DiscoveryState) -> dict:
    """LLM evaluates candidate URLs; returns those worth adding to sources.yaml."""
    existing_domains = _load_existing_domains()

    approved = _score_candidate_urls(state["candidate_urls"], existing_domains)
    return {"approved_sources": approved}


def update_sources(state: DiscoveryState) -> dict:
    """Append approved sources to sources.yaml and commit."""
    approved = state.get("approved_sources", [])
    if not approved:
        return {}
    n = len(approved)
    _write_and_commit_sources(approved, f"chore: weekly source discovery — {n} new source(s) added")
    return {}


# ---------------------------------------------------------------------------
# Daily graph: expand sources when results are thin
# ---------------------------------------------------------------------------

def expand_sources_if_thin(state: DailyState) -> dict:
    """
    Triggered by the daily graph when no roles clear the score threshold.

    Runs a mini-discovery pass: generates SERP queries from ambition.md,
    collects new domains via Brave Search, scores them, and appends any
    approved sources to sources.yaml with a git commit. Returns an
    expansion_note that the digest composer renders in the email footer.
    """
    scored = state.get("scored_jobs", [])
    above_threshold = [s for s in scored if "BELOW THRESHOLD" not in s.rationale]
    if above_threshold:
        # Enough results — skip expansion
        return {"expansion_note": ""}

    print("No roles above threshold — running inline source expansion...")

    with open(CONFIG_DIR / "ambition.md") as f:
        ambition = f.read()

    # Generate queries
    prompt = f"""Based on this statement of ambition, generate 10 targeted SERP search queries to find job boards, careers pages, and VC portfolio pages relevant to this candidate.

{ambition}

Focus on: defense tech, physical AI, robotics, autonomous systems, geospatial/ISR, hard science R&D, quantitative research.
Return exactly 10 queries, one per line. No numbering, no bullets."""

    msg = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    queries = [l.strip() for l in msg.content[0].text.strip().split("\n") if l.strip()][:10]
    print(f"Expansion: generated {len(queries)} SERP queries")

    # Run SERP
    domain_to_url: dict[str, str] = {}
    for query in queries:
        try:
            results = brave_search(query, count=10)
        except Exception as e:
            print(f"Expansion SERP error for '{query}': {e}")
            continue
        for r in results:
            domain = urlparse(r["url"]).netloc
            if domain and domain not in domain_to_url:
                domain_to_url[domain] = r["url"]

    candidate_urls = list(domain_to_url.values())
    print(f"Expansion SERP: {len(candidate_urls)} unique domains")

    # Score and write
    existing_domains = _load_existing_domains()
    approved = _score_candidate_urls(candidate_urls, existing_domains)

    if approved:
        n = len(approved)
        try:
            _write_and_commit_sources(
                approved,
                f"chore: daily expansion — {n} new source(s) added (thin results)",
            )
            note = f"{n} new source(s) added to the search list for tomorrow's run."
        except Exception as e:
            print(f"Expansion commit failed: {e}")
            note = f"{n} new source(s) identified but commit failed: {e}"
    else:
        note = "No new sources found during expansion."

    print(f"Expansion complete: {note}")
    return {"expansion_note": note}
