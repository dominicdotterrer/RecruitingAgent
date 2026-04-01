"""
Weekly site-discovery agent.

Generates SERP queries from ambition.md, runs them via Brave Search,
scores each new domain with an LLM, and appends approved sources to
sources.yaml with a git commit.
"""
import os
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import yaml

from agent.state import DiscoveryState
from agent.tools.serp_tool import brave_search

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


def score_sites(state: DiscoveryState) -> dict:
    """LLM evaluates candidate URLs; returns those worth adding to sources.yaml."""
    # Load existing source URLs to avoid duplicates
    with open(CONFIG_DIR / "sources.yaml") as f:
        existing = yaml.safe_load(f)

    existing_domains: set[str] = set()
    for entries in existing.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            for key in ("url", "portfolio_url"):
                if key in entry:
                    existing_domains.add(urlparse(entry[key]).netloc)

    # Filter to truly new domains
    new_candidates = [
        u for u in state["candidate_urls"]
        if urlparse(u).netloc not in existing_domains
    ][:50]

    if not new_candidates:
        print("No new candidate domains to evaluate")
        return {"approved_sources": []}

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
                {
                    "url": url,
                    "type": site_type,
                    "discovered_date": today,
                    "discovery_reason": reason,
                }
            )

    print(f"Site scorer: {len(approved)} new source(s) approved")
    return {"approved_sources": approved}


def update_sources(state: DiscoveryState) -> dict:
    """Append approved sources to sources.yaml and commit."""
    approved = state.get("approved_sources", [])
    if not approved:
        return {}

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
        if category not in sources:
            sources[category] = []
        sources[category].append(source)

    with open(sources_path, "w") as f:
        yaml.dump(sources, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    n = len(approved)
    subprocess.run(["git", "add", str(sources_path)], check=True)
    subprocess.run(
        [
            "git", "commit", "-m",
            f"chore: weekly source discovery — {n} new source(s) added",
        ],
        check=True,
    )
    subprocess.run(["git", "push"], check=True)
    print(f"Committed and pushed {n} new source(s) to sources.yaml")
    return {}
