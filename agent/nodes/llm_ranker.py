"""LLM ranker: scores each job 0–10 against profile.md and ambition.md."""
import os
from pathlib import Path

import anthropic
import yaml

from agent.state import DailyState, JobPosting, ScoredJob

CONFIG_DIR = Path("config")


def _load_configs() -> tuple[str, str, int]:
    with open(CONFIG_DIR / "profile.md") as f:
        profile = f.read()
    with open(CONFIG_DIR / "ambition.md") as f:
        ambition = f.read()
    with open(CONFIG_DIR / "keyword_rules.yaml") as f:
        rules = yaml.safe_load(f)
    threshold = int(rules.get("llm_score_threshold", 6))
    return profile, ambition, threshold


def _score_job(client: anthropic.Anthropic, job: JobPosting, profile: str, ambition: str) -> ScoredJob:
    prompt = f"""You are evaluating a job posting against a candidate's profile and statement of ambition.

## Candidate Profile
{profile}

## Statement of Ambition
{ambition}

## Job Posting
**Title:** {job.title}
**Company:** {job.company}
**URL:** {job.url}

**Description:**
{job.description[:3000]}

---

Score this role from 0 to 10 against the candidate's profile and ambition using the scoring guidance in the ambition document. Apply hard filters as specified: any role violating a hard filter must score no higher than 3.

Penalize roles that are operationally heavy or managerial rather than research-heavy, even if the title sounds right. Reward roles that expose genuine new intellectual territory.

Respond in exactly this format (no other text):
SCORE: <integer 0-10>
RATIONALE: <2-3 sentences explaining the match or mismatch; note the strongest signal in either direction>"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = msg.content[0].text.strip()
    score = 0
    rationale = ""
    for line in text.split("\n"):
        if line.startswith("SCORE:"):
            try:
                score = max(0, min(10, int(line.split(":", 1)[1].strip())))
            except ValueError:
                pass
        elif line.startswith("RATIONALE:"):
            rationale = line.split(":", 1)[1].strip()

    return ScoredJob(posting=job, score=score, rationale=rationale)


def llm_ranker(state: DailyState) -> dict:
    if not state.get("filtered_jobs"):
        return {"scored_jobs": []}

    profile, ambition, threshold = _load_configs()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    scored: list[ScoredJob] = []
    for job in state["filtered_jobs"]:
        result = _score_job(client, job, profile, ambition)
        scored.append(result)

    scored.sort(key=lambda x: x.score, reverse=True)

    above_threshold = [s for s in scored if s.score >= threshold]
    if above_threshold:
        print(f"LLM ranker: {len(above_threshold)} role(s) at or above threshold {threshold}")
        return {"scored_jobs": above_threshold}

    # Fallback: include top 3 regardless of score, clearly flagged
    top3 = scored[:3]
    for s in top3:
        s.rationale = f"[BELOW THRESHOLD] {s.rationale}"
    print(f"LLM ranker: no roles above threshold — including top {len(top3)} as fallback")
    return {"scored_jobs": top3}
