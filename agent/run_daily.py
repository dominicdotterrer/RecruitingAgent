"""Entrypoint for the daily digest run. Called by GitHub Actions."""
from dotenv import load_dotenv

load_dotenv()

from agent.graph import build_daily_graph  # noqa: E402 (after load_dotenv)

if __name__ == "__main__":
    graph = build_daily_graph()
    result = graph.invoke(
        {
            "sources": [],
            "raw_jobs": [],
            "new_jobs": [],
            "filtered_jobs": [],
            "scored_jobs": [],
            "digest_html": "",
            "email_sent": False,
        }
    )
    status = "sent" if result.get("email_sent") else "NOT sent"
    scored = result.get("scored_jobs", [])
    print(f"Done. Digest {status}. {len(scored)} role(s) included.")
