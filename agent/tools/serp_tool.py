"""Brave Search API wrapper."""
import os

import httpx

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def brave_search(query: str, count: int = 10) -> list[dict]:
    """
    Run a web search via Brave Search API.

    Returns a list of dicts with keys: url, title, description.
    """
    api_key = os.environ["BRAVE_SEARCH_API_KEY"]
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": min(count, 20)}

    with httpx.Client(timeout=15) as client:
        resp = client.get(BRAVE_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()

    results = resp.json().get("web", {}).get("results", [])
    return [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "description": r.get("description", ""),
        }
        for r in results
        if r.get("url")
    ]
