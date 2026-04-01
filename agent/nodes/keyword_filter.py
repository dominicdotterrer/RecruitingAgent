"""Rule-based pre-filter. Fast pass/fail before spending LLM tokens."""
from pathlib import Path

import yaml

from agent.state import DailyState, JobPosting

CONFIG_DIR = Path("config")


def keyword_filter(state: DailyState) -> dict:
    with open(CONFIG_DIR / "keyword_rules.yaml") as f:
        rules = yaml.safe_load(f)

    exclude_titles = [t.lower() for t in rules.get("exclude_titles", [])]
    exclude_domains = [d.lower() for d in rules.get("exclude_domains", [])]
    require_any = [r.lower() for r in rules.get("require_any", [])]

    filtered: list[JobPosting] = []
    for job in state["new_jobs"]:
        title_lower = job.title.lower()
        desc_lower = job.description.lower()
        combined = title_lower + " " + desc_lower

        # Hard exclude: title contains an excluded term
        if any(ex in title_lower for ex in exclude_titles):
            continue

        # Hard exclude: title signals an excluded domain
        if any(ex in title_lower for ex in exclude_domains):
            continue

        # Require at least one positive signal in title or description
        if require_any and not any(req in combined for req in require_any):
            continue

        filtered.append(job)

    print(f"Keyword filter: {len(state['new_jobs'])} → {len(filtered)} jobs")
    return {"filtered_jobs": filtered}
