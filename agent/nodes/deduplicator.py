"""
Postgres-backed deduplication.

Schema (created by scripts/init_db.py):
    seen_jobs(id TEXT PRIMARY KEY, first_seen TIMESTAMPTZ)

Jobs are suppressed for 30 days after first appearance. No job content is
stored — only the ID hash and timestamp.
"""
import os
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

from agent.state import DailyState, JobPosting

_SUPPRESS_DAYS = 30


def _get_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def deduplicate(state: DailyState) -> dict:
    """Filter raw_jobs to only those not seen in the last 30 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_SUPPRESS_DAYS)

    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM seen_jobs WHERE first_seen > %s",
                (cutoff,),
            )
            seen_ids = {row[0] for row in cur.fetchall()}

    # Also deduplicate within the current batch (same job from multiple sources)
    seen_in_batch: set[str] = set()
    new_jobs: list[JobPosting] = []
    for job in state["raw_jobs"]:
        if job.id not in seen_ids and job.id not in seen_in_batch:
            new_jobs.append(job)
            seen_in_batch.add(job.id)

    print(f"Deduplicator: {len(state['raw_jobs'])} raw → {len(new_jobs)} new")
    return {"new_jobs": new_jobs}


def persist_seen(state: DailyState) -> dict:
    """
    Record all newly-processed jobs so they aren't re-evaluated for 30 days.
    Persists new_jobs (everything that passed dedup), not just the scored subset.
    """
    jobs = state.get("new_jobs", [])
    if not jobs:
        return {}

    now = datetime.now(timezone.utc)
    rows = [(job.id, now) for job in jobs]

    with _get_conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO seen_jobs (id, first_seen) VALUES %s ON CONFLICT (id) DO NOTHING",
                rows,
            )
        conn.commit()

    print(f"Persisted {len(rows)} job ID(s) to seen_jobs")
    return {}
