"""
Creates the seen_jobs table in Postgres.

Run once before the first workflow execution:
    python -m scripts.init_db

Requires DATABASE_URL in the environment (or a .env file).
"""
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def init_db() -> None:
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    id         TEXT                     PRIMARY KEY,
                    first_seen TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_seen_jobs_first_seen
                ON seen_jobs (first_seen)
                """
            )
    conn.close()
    print("Database initialized: seen_jobs table ready.")


if __name__ == "__main__":
    init_db()
