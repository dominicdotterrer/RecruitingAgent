"""Entrypoint for the weekly site-discovery run. Called by GitHub Actions."""
from dotenv import load_dotenv

load_dotenv()

from agent.graph import build_discovery_graph  # noqa: E402 (after load_dotenv)

if __name__ == "__main__":
    graph = build_discovery_graph()
    result = graph.invoke(
        {
            "ambition": "",
            "profile": "",
            "serp_queries": [],
            "candidate_urls": [],
            "approved_sources": [],
        }
    )
    approved = result.get("approved_sources", [])
    print(f"Done. {len(approved)} new source(s) added to sources.yaml.")
