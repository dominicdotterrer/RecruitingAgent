"""Formats the ranked job list into a clean HTML email digest."""
from datetime import date

from agent.state import DailyState, ScoredJob

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, sans-serif;
    max-width: 660px;
    margin: 0 auto;
    padding: 24px 16px;
    color: #1a1a1a;
    background: #fff;
  }}
  h1 {{
    font-size: 20px;
    font-weight: 700;
    border-bottom: 2px solid #1a1a1a;
    padding-bottom: 10px;
    margin-bottom: 24px;
  }}
  h2 {{
    font-size: 12px;
    font-weight: 600;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 32px 0 12px 0;
  }}
  .job {{
    border: 1px solid #e4e4e4;
    border-radius: 6px;
    padding: 14px 16px;
    margin-bottom: 12px;
  }}
  .job-title {{
    font-size: 15px;
    font-weight: 600;
    margin: 0 0 4px 0;
  }}
  .job-title a {{
    color: #1a1a1a;
    text-decoration: none;
  }}
  .job-title a:hover {{
    text-decoration: underline;
  }}
  .job-meta {{
    font-size: 12px;
    color: #777;
    margin: 0 0 10px 0;
  }}
  .score-badge {{
    display: inline-block;
    background: #1a1a1a;
    color: #fff;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 700;
    vertical-align: middle;
  }}
  .rationale {{
    font-size: 13px;
    line-height: 1.55;
    color: #444;
    margin: 0;
  }}
  .below-threshold .score-badge {{
    background: #999;
  }}
  .footer {{
    margin-top: 40px;
    font-size: 11px;
    color: #aaa;
    border-top: 1px solid #eee;
    padding-top: 14px;
  }}
  .empty {{
    font-size: 14px;
    color: #888;
    padding: 20px 0;
  }}
</style>
</head>
<body>
<h1>Job Digest &mdash; {date}</h1>
{body}
<div class="footer">
  {scanned} roles scanned &nbsp;&middot;&nbsp;
  {filtered} passed keyword filter &nbsp;&middot;&nbsp;
  {included} included in digest
</div>
</body>
</html>"""


def _render_job(s: ScoredJob, css_class: str = "") -> str:
    below = "BELOW THRESHOLD" in s.rationale
    rationale = s.rationale.replace("[BELOW THRESHOLD] ", "")
    badge_label = f"{int(s.score)}/10"
    return f"""\
<div class="job{' ' + css_class if css_class else ''}">
  <p class="job-title"><a href="{s.posting.url}">{s.posting.title}</a></p>
  <p class="job-meta">
    {s.posting.company}
    &nbsp;&middot;&nbsp;
    <span class="score-badge">{badge_label}</span>
    &nbsp;&middot;&nbsp;
    {s.posting.source}
  </p>
  <p class="rationale">{rationale}</p>
</div>"""


def _section(title: str, jobs: list[ScoredJob], css_class: str = "") -> str:
    if not jobs:
        return ""
    cards = "\n".join(_render_job(s, css_class) for s in jobs)
    return f"<h2>{title}</h2>\n{cards}\n"


def compose_digest(state: DailyState) -> dict:
    scored = state.get("scored_jobs", [])
    raw_count = len(state.get("raw_jobs", []))
    filtered_count = len(state.get("filtered_jobs", []))

    strong = [s for s in scored if s.score >= 8 and "BELOW THRESHOLD" not in s.rationale]
    good = [s for s in scored if 6 <= s.score < 8 and "BELOW THRESHOLD" not in s.rationale]
    below = [s for s in scored if "BELOW THRESHOLD" in s.rationale]

    if scored:
        body = (
            _section("Strong match (8–10)", strong)
            + _section("Good match (6–7)", good)
            + _section("Best available — below threshold", below, "below-threshold")
        )
    else:
        body = '<p class="empty">No new roles found today.</p>'

    html = _HTML.format(
        date=date.today().strftime("%B %d, %Y"),
        body=body,
        scanned=raw_count,
        filtered=filtered_count,
        included=len(scored),
    )
    return {"digest_html": html}
