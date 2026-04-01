# Job Search Agent — Development Plan

## Overview

A LangGraph-based agent that runs daily via GitHub Actions, discovers relevant job postings from a curated and dynamically expanding set of sources, scores them against your resume and statement of ambition, and delivers a ranked digest to your email. A SERP-driven site discovery sub-agent runs on a slower cadence (weekly) to expand the source list.

---

## Repository Structure

```
job-search-agent/
├── .github/
│   └── workflows/
│       ├── daily_digest.yml        # runs daily at 7am ET
│       └── weekly_discovery.yml    # runs Sunday night
├── agent/
│   ├── graph.py                    # LangGraph graph definition
│   ├── nodes/
│   │   ├── scraper.py              # fetches job listings from sources
│   │   ├── keyword_filter.py       # rule-based pre-filter
│   │   ├── llm_ranker.py           # LLM re-ranking against profile+ambition
│   │   ├── deduplicator.py         # checks SQLite for seen roles
│   │   ├── digest_composer.py      # formats email digest
│   │   └── site_discoverer.py      # SERP-based source expansion
│   ├── tools/
│   │   ├── serp_tool.py            # wraps SerpAPI or Brave Search API
│   │   ├── scrape_tool.py          # wraps crawl4ai or similar
│   │   └── email_tool.py           # sends via Brevo SMTP
│   └── state.py                    # LangGraph state schema
├── config/
│   ├── profile.md                  # your resume in plain text form
│   ├── ambition.md                 # your statement of ambition
│   ├── keyword_rules.yaml          # include/exclude keyword lists
│   └── sources.yaml                # the live source list (git-tracked)
├── db/
│   └── jobs.db                     # SQLite (gitignored)
├── scripts/
│   └── init_db.py                  # creates schema on first run
├── tests/
│   └── ...
├── requirements.txt
└── README.md
```

---

## The Two Core Artifacts

Before any code is written, these two files need to exist and be treated as first-class inputs that all agent behavior derives from.

**`config/profile.md`** — A distilled version of your resume optimized for semantic matching, not human reading. Should emphasize: mathematical background, problem formalization methodology, domain expertise areas, and seniority signals. Strip operational/management language that you are deliberately downplaying.

**`config/ambition.md`** — Your statement of ambition. This should answer: What class of problems do you want to work on? What environments are fulfilling (zero-to-one R&D, not one-to-ten scaling)? What would make a role feel wrong even if the title fits? What sectors excite you (defense tech, hard science, physical AI)? This document should be written in first person and be roughly 300–500 words. It becomes the primary input to the LLM ranker and the SERP discovery agent.

---

## Agent Graph (LangGraph)

### Daily Digest Graph

```
START
  └─→ [load_sources]              # reads sources.yaml
        └─→ [scrape_sources]      # parallel fan-out across all sources
              └─→ [deduplicate]          # filters already-seen job IDs
                    └─→ [keyword_filter]       # rule-based exclude/include
                          └─→ [llm_ranker]           # scores 0-10 against profile+ambition
                                └─→ [compose_digest]       # formats ranked results
                                      └─→ [send_email]
                                            └─→ [persist_seen]   # writes to SQLite
                                                  └─→ END
```

### Weekly Discovery Graph

```
START
  └─→ [load_ambition + load_profile]
        └─→ [generate_serp_queries]       # LLM generates 10-15 search strings
              └─→ [run_serp]              # executes searches, collects result URLs
                    └─→ [score_sites]           # LLM evaluates each site for relevance
                          └─→ [update_sources_yaml]   # appends new sources, commits to git
                                └─→ END
```

---

## Node Specifications

### `scraper.py`
- Maintains a registry of scraper strategies keyed by source type: `careers_page`, `job_board`, `rss_feed`, `vc_portfolio`
- VC portfolio pages need a two-step scrape: first extract portfolio company list, then visit each company's careers page
- Use `crawl4ai` for JS-rendered pages (most modern careers pages require this); `httpx` + `BeautifulSoup` for static pages
- Each scraped role should produce a normalized `JobPosting` object: `{id, title, company, url, description, source, scraped_at}`
- Rate limit politely — add random delays, respect robots.txt

### `keyword_filter.py`
- Reads `config/keyword_rules.yaml`
- Structure of rules file:
```yaml
exclude_titles:
  - "junior"
  - "associate"
  - "intern"
  - "staff engineer"
exclude_domains:
  - "marketing"
  - "sales"
require_any:
  - "research"
  - "scientist"
  - "R&D"
  - "principal"
  - "director"
  - "applied science"
llm_score_threshold: 6
```
- Fast pass/fail before spending LLM tokens

### `llm_ranker.py`
- For each role surviving keyword filter, sends a structured prompt to Claude containing: (1) the job description, (2) `profile.md`, (3) `ambition.md`
- Returns a score 0–10 plus a 2–3 sentence rationale explaining the match
- Prompt should explicitly ask the model to penalize roles that are operationally heavy vs. research-heavy, even if the title sounds right
- Only roles scoring ≥ 6 make it into the digest (threshold configurable in `keyword_rules.yaml`)

### `deduplicator.py`
- SQLite schema:
```sql
CREATE TABLE seen_jobs (
  id TEXT PRIMARY KEY,       -- hash of (company + title + url)
  first_seen DATE,
  last_seen DATE,
  score REAL,
  included_in_digest BOOLEAN
);
```
- A role resurfaces in the digest only if its description has changed since last seen

### `digest_composer.py`
- Groups roles by score tier: **Strong match (8–10)**, **Good match (6–7)**
- For each role: title, company, link, score, LLM rationale (2–3 sentences), source
- Email format: plain HTML, clean and readable on mobile
- Footer: total roles scanned, total passing keyword filter, total included in digest

### `site_discoverer.py`
- LLM generates SERP queries derived from `ambition.md`, for example:
  - `"R&D scientist physical AI defense site:jobs.lever.co"`
  - `"principal research scientist zero-to-one hard tech"`
  - `"mathematician ML research director careers"`
- Runs queries via SERP API, collects unique domains from results
- LLM scores each new domain: is this a job board, a company careers page, or irrelevant?
- Writes approved new sources into `sources.yaml` with metadata: `{url, type, discovered_date, discovery_query}`
- Commits updated `sources.yaml` directly to main (or opens a PR — operator preference)

---

## Seed `sources.yaml`

```yaml
job_boards:
  - url: https://www.mathjobs.org/jobs
    type: job_board
    scraper: mathjobs
  - url: https://www.linkedin.com/jobs/search/
    type: job_board
    scraper: linkedin
    search_terms: ["research scientist", "principal scientist", "R&D director"]
  - url: https://www.indeed.com
    type: job_board
    scraper: indeed
  - url: https://jobs.usa.gov
    type: job_board
    scraper: usajobs

company_careers:
  - company: Anduril Industries
    url: https://www.anduril.com/open-roles/
    type: careers_page
  - company: Shield AI
    url: https://shield.ai/careers/
    type: careers_page
  - company: Palantir
    url: https://www.palantir.com/careers/
    type: careers_page
  - company: Jane Street
    url: https://www.janestreet.com/join-jane-street/open-roles/
    type: careers_page
  - company: Two Sigma
    url: https://careers.twosigma.com
    type: careers_page
  - company: MITRE
    url: https://careers.mitre.org
    type: careers_page

vc_portfolios:
  - name: Lux Capital
    portfolio_url: https://luxcapital.com/companies
    type: vc_portfolio
  - name: In-Q-Tel
    portfolio_url: https://www.iqt.org/portfolio/
    type: vc_portfolio
  - name: a16z Defense
    portfolio_url: https://a16z.com/portfolio/
    type: vc_portfolio
    filter: defense
```

---

## GitHub Actions Workflows

### `daily_digest.yml`
```yaml
on:
  schedule:
    - cron: '0 11 * * *'   # 7am ET daily
  workflow_dispatch:         # allows manual trigger for testing
```

### `weekly_discovery.yml`
```yaml
on:
  schedule:
    - cron: '0 4 * * 0'    # Sunday night / Monday 12am ET
  workflow_dispatch:
```

### Secrets required
- `ANTHROPIC_API_KEY`
- `SERP_API_KEY`
- `BREVO_SMTP_PASSWORD`

### SQLite persistence across runs
GitHub Actions runners are ephemeral — the db does not survive between runs. Recommended approach for v1: after each run, commit `jobs.db` to a dedicated private branch (e.g. `state/main`). The workflow checks out that branch at the start of each run to restore state. No external dependencies required.

---

## Build Sequence

Implement in this order — each phase is independently testable before proceeding.

### Phase 1 — Foundation
- Repo scaffold, `state.py`, `init_db.py`, seed `sources.yaml`
- **Write `profile.md` and `ambition.md` before touching any other code** — these are the inputs everything derives from

### Phase 2 — Scraping
- Implement `scrape_tool.py` with `crawl4ai`
- Implement scrapers for three sources: one job board (Indeed), one careers page (Anduril), one VC portfolio (Lux Capital)
- Output: list of normalized `JobPosting` objects to stdout for inspection

### Phase 3 — Filtering pipeline
- `keyword_filter.py` with the rules YAML
- `deduplicator.py` with SQLite
- `llm_ranker.py` — test against a handful of real postings before wiring into the graph

### Phase 4 — Digest and delivery
- `digest_composer.py`
- `email_tool.py` via Brevo SMTP
- End-to-end local test: run the full daily graph, receive the email

### Phase 5 — GitHub Actions wiring
- `daily_digest.yml` workflow
- SQLite persistence via private branch commit
- Secrets configuration and first live run

### Phase 6 — Site discoverer
- `site_discoverer.py`
- `weekly_discovery.yml` workflow
- Test SERP query generation from `ambition.md`
- Test `sources.yaml` update and commit logic

---

## Open Questions to Resolve Before Starting

**1. SERP API provider**
SerpAPI is the most reliable but costs ~$50/mo at moderate volume. Brave Search API is cheaper with a generous free tier. Decide before Phase 2.

**2. LinkedIn scraping**
LinkedIn aggressively blocks scrapers. Options:
- Official LinkedIn Jobs API (requires partnership approval)
- Third-party provider such as Apify's LinkedIn scraper
- Exclude LinkedIn from automated scraping and check it manually

Decide before Phase 2 so the LinkedIn source entry in `sources.yaml` can be configured correctly.

**3. SQLite persistence**
Committing the db to a private branch is simple but adds a git commit on every run. A free-tier Supabase Postgres instance is a cleaner alternative if you are open to one external dependency. Decide before Phase 5.
