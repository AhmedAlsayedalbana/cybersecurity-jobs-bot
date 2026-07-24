# Cybersecurity Jobs Bot — v53

> **v53: LinkedIn-first, Egypt-priority, noise-reduced Greenhouse, 4-layer URL dedup.**

## v58.1 (merged): v58-verified base + official-sources extras

This build merges the two parallel variants of the bot back into one:

- **Base:** `v58-verified` — correct `boards-api.greenhouse.io` endpoint, Lever +
  SmartRecruiters ATS support, direct free remote/contract feeds, the strict
  60/40 LinkedIn cap enforced both at pool-build time and again at Telegram
  delivery time, `ENABLE_PROXY_POOL` opt-in gating, and the fuller test suite.
- **Pulled in from `official-sources`:**
  - **Pretrained ML model** — `ml_models/cybersec_title_model.joblib` is now
    shipped in the repo, so `ml_filter.py` loads a trained classifier on the
    very first run instead of bootstrapping from the small seed list.
  - **"Relaxing quotas" fallback** — `intelligence/pool_builder.py` now has a
    last-resort step: if, after the strict 60/40 enforcement, the pool is
    still below `MIN_POOL_SIZE` (a genuine shortage of non-LinkedIn/secondary
    supply that cycle), it relaxes the LinkedIn cap just enough to reach the
    minimum instead of shipping an empty/short run. This only ever fires as a
    fallback — normal runs still get the strict v58 ratio; `official-sources`
    used this as its *only* behaviour, which is what silently pushed the
    ratio to ~70/30 there.
  - Test coverage updated to match: `test_min_pool_size_relaxes_linkedin_cap_as_last_resort`
    replaces the old "returns empty pool" assertion.

## v58: Public Contract Feeds and Final 60/40 Delivery Balance

- Corrected all Greenhouse Job Board requests to `boards-api.greenhouse.io`.
- Added 13 individually monitored official ATS sources using Greenhouse, Lever, Ashby, and SmartRecruiters public APIs.
- Public ATS calls bypass the optional proxy pool; proxy routing now requires `ENABLE_PROXY_POOL=true`, preventing expired proxy credentials from causing 402 failures.
- LinkedIn uses a 600-second, 30-query specialty plan covering GRC, SOC, IAM, AppSec, DevSecOps, threat intelligence, red team, bug bounty, and penetration-testing roles across Egypt, the Gulf, and remote work. Result cards are parsed directly, so one search request can yield up to 25 jobs without a separate detail request per job.
- The 60/40 cap is enforced twice: in the selected pool and again at Telegram delivery time. Channel routing can duplicate a job into a geo and a topic thread, so the delivery gate measures the messages actually sent and holds extra LinkedIn jobs rather than silently breaking the ratio.
- JSearch is enabled automatically as soon as `RAPIDAPI_KEY` is set in GitHub Actions secrets; without the key it is omitted from the run instead of being reported as a misleading empty success.
- Added four direct, free remote/contract feeds: Remotive API, RemoteOK API, We Work Remotely RSS, and Arbeitnow API. They keep canonical URLs, source posting dates, and tag explicit `Contract / Freelance` roles.
- HTML marketplace pages that are routinely session/WAF-bound (Upwork, Freelancer, Mostaql, Contra, PeoplePerHour, Guru, Workana, Bayt, GulfTalent, Tanqeeb, and Akhtaboot) are now diagnostic-only. `Fiverr`, `Khamsat`, and `Toptal` are excluded because they expose service offers rather than public client-job feeds. This removes false "0 jobs" and proxy-402 noise from normal runs.

## What's New in v53

| Fix | Description |
|-----|-------------|
| ✅ **`Threat Intelligence Researcher` false-reject fixed** | Pattern now in `intelligence/patterns.py` SOC domain |
| ✅ **LinkedIn Egypt CORE queries expanded** | +6 Egypt queries, Arabic queries, Alexandria/Giza/Mansoura |
| ✅ **LinkedIn budget increased** | 300s (was 240s), 0.65 rps (was 0.55), 5 concurrency (was 4) |
| ✅ **LinkedIn EXPANSION queries expanded** | +12 queries: Arabic, security specializations, more remote |
| ✅ **Wazzif (وظف) added** | New Egyptian job board, priority 19 |
| ✅ **Akhtaboot Egypt added** | MENA regional board with Egypt filter, priority 19 |
| ✅ **DrJobPro + Forasna added** | Egypt-specific boards via `sources/egypt_boards.py` |
| ✅ **Greenhouse Big Tech reduced** | From 21 → 7 companies (only security-heavy ones kept) |
| ✅ **Greenhouse Cybersec expanded** | From 11 → 27 dedicated security vendors |
| ✅ **Greenhouse double-fetch fixed** | `expanded_sources.GREENHOUSE_TIER1` emptied (was duplicating `greenhouse_expanded`) |
| ✅ **Per-batch Greenhouse budget** | Cybersec=120s, BigTech=60s, SaaS=60s — prevents budget blowout |
| ✅ **URL-normalized dedup layer added** | Catches same job from different source keys (Layer 1 enhancement) |
| ✅ **Khamsat + Freelancer in registry** | Now official sources in `source_registry.py` Tier 3 |
| ✅ **Truelancer feeds expanded** | +3 RSS feeds (pentesting, info-sec, security-audit) |
| ✅ **Source priority order** | LinkedIn(10) → Wuzzuf(15-16) → Egypt Boards(17-19) → Freelance(20) → Greenhouse(30+) |

A Telegram bot that automatically scrapes, filters, deduplicates, scores, and routes
cybersecurity job listings to dedicated topic channels. Runs on GitHub Actions every
3 hours with zero infrastructure cost.

---

## Architecture

```
GitHub Actions (cron: */3h)
        │
        ▼
  main.py  ─── Async fetch ───► 46+ sources (LinkedIn, Google Jobs, Greenhouse, ...)
        │
        ├─► models.py          — Job dataclass + recency filter
        ├─► ai_filter.py       — 4-layer hybrid classification (Ultimate v50+)
        │     Layer 1: False-positive patterns (regex — physical/sales/HR)
        │     Layer 2: Modern cybersec title patterns (Arabic + English)
        │     Layer 3: Context signal scoring (tools, frameworks, certs)
        │     Layer 4: Claude Haiku API (borderline cases only, cached)
        │     Offline fallback: intelligence.classify_cyber_intent
        ├─► intelligence/      — Modular classification engine (AT v47)
        │     geo.py           — Egypt / Gulf / Remote / Global routing
        │                          (includes Arabic frozenset: مصر/القاهرة/الجيزة)
        │     intent.py        — Cyber-intent gate (hard reject / accept)
        │     seniority.py     — Entry-level detection
        │     domain.py        — SOC / Pentest / AppSec / Cloud / GRC
        │     patterns.py      — 305-line exhaustive pattern library
        │     pool_builder.py  — Final pool assembly with quota enforcement
        │     dedupe.py        — Fuzzy fingerprint deduplication
        │     llm_classifier.py— LLM borderline classification (optional)
        ├─► scoring.py         — Bayesian freshness + ML bonus + diversity rerank (V32)
        ├─► dedup.py           — 3-layer deduplication (fingerprint + URL + title)
        ├─► database.py        — SQLite v41 (WAL, persistent fingerprints, retry queue)
        ├─► ml_filter.py       — Local ML model (cybersec_title_model.joblib)
        └─► telegram_sender.py — Route to topic channels + Markdown formatting
```

---

## What's Merged

| Feature | Source | Notes |
|---------|--------|-------|
| `intelligence/` module | AT v47 | 10-file modular engine, 305-line patterns |
| `ai_filter.py` (4-layer) | AKM + merged | Arabic titles, Claude Haiku API, offline fallback |
| `scoring.py` V32 | AKM | Bayesian decay, ML bonus, diversity rerank |
| `database.py` v41 | AT/AKM | WAL mode, persistent fingerprints, retry queue |
| `intelligence/geo.py` | MCO | Arabic frozenset (مصر/القاهرة/الجيزة/الإسكندرية) |
| `source_registry.py` | Merged | Tier-based + all optional AKM sources (gulf_boards, linkedin_api) |
| `ml_models/` | MCO | `cybersec_title_model.joblib` — offline ML classifier |
| CI/CD workflow | Merged | 3h schedule + DB persistence + dry_run + source_override |
| Tests | Merged | 5 test files, 1,295 lines |
| Config | Merged | 7d freshness, 3h dedup, LLM enabled by default |

---

## Channels & Topics

| Channel | Topic | Filter |
|---------|-------|--------|
| Egypt | `TOPIC_EGYPT` | Egypt onsite + hybrid |
| Gulf | `TOPIC_GULF` | GCC countries |
| Remote | `TOPIC_REMOTE` | Fully remote, worldwide |
| SOC / Blue Team | `TOPIC_SOC` | Detection, SIEM, DFIR |
| Pentest / Red Team | `TOPIC_PENTEST` | Offensive, bug bounty |
| AppSec | `TOPIC_APPSEC` | SAST, DAST, DevSecOps |
| Cloud Security | `TOPIC_CLOUDSEC` | AWS/Azure/GCP security |
| GRC | `TOPIC_GRC` | Compliance, ISO 27001, risk |
| Security Engineering | `TOPIC_SECENG` | Infra security, IAM |
| Network Security | `TOPIC_NETWORKSEC` | Firewall, IDS/IPS, zero trust |
| Internships | `TOPIC_INTERNSHIPS` | Entry-level + trainee |

---

## Scoring System

The V32 scoring model uses **Bayesian freshness decay** and prioritizes the Egyptian market.

| Factor | Points |
|--------|--------|
| 🇪🇬 Egypt location | **+8** |
| 🌙 Gulf location | **+6** |
| 🌍 Remote | +5 |
| Hybrid (Remote + Egypt/Gulf) | +2 bonus |
| SOC Analyst / SOC Engineer | **+5** |
| Penetration Testing / Red Team | **+5** |
| Network Security | **+5** |
| SIEM / Splunk / QRadar / Sentinel | +4 each |
| Blue Team / DFIR / Threat Hunting | +4 each |
| Ethical Hacking / Bug Bounty | +4 each |
| Firewall / Palo Alto / Fortinet / Cisco | +4 each |
| Cloud Security / AWS / Azure | +4 each |
| Zero Trust / Network Defense | +4 each |
| Vulnerability / AppSec / DevSecOps | +3 each |
| Bayesian freshness (0–6 pts, smooth decay) | up to +6 |
| Entry-level keywords | +3 |
| Experience: 0–2 years | +2 |
| Older than 7 days | penalty via decay |

---

## Setup

### 1. Fork and configure secrets

In **Settings → Secrets and variables → Actions**, add:

| Secret | Required | Description |
|--------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | Supergroup ID |
| `TOPIC_EGYPT` ... `TOPIC_INTERNSHIPS` | ✅ | Telegram topic `message_thread_id` values |
| `HEALTH_REPORT_CHAT_ID` | Optional | Health report destination, defaults to `TELEGRAM_CHAT_ID` |
| `ANTHROPIC_API_KEY` | ⭐ Recommended | Enables Layer 4 AI classification |
| `RAPIDAPI_KEY` | Optional | JSearch Enhanced source |
| `SERPAPI_KEY` | Optional | Google Intelligence source |
| `LINKEDIN_COOKIES` | Optional | LinkedIn scraping cookies |

### 2. Run manually first (seed mode)

Use **Actions → Run workflow → seed_mode: true** to mark existing jobs as seen
without sending them. This prevents a flood on first real run.

### 3. Schedule

The bot runs automatically every 3 hours via GitHub Actions cron.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_JOB_AGE_DAYS` | `7` | Hard-block jobs older than this (Bayesian decay handles 5-7d) |
| `MAX_JOBS_PER_CHANNEL` | `10` | Max unique jobs per channel per run |
| `MIN_POOL_SIZE` | `5` | Minimum final pool when enough qualified jobs exist |
| `LINKEDIN_TOTAL_BUDGET_SECONDS` | `600` | Hard cap for LinkedIn Unified |
| `LINKEDIN_PAGES_PER_QUERY` | `4` | Public result pages fetched per focused LinkedIn search |
| `LINKEDIN_DETAILS_PER_QUERY` | `6` | Detail-page fallback only for incomplete result cards |
| `LINKEDIN_POOL_CAP_RATIO` | `0.60` | Maximum LinkedIn share of the final pool |
| `NON_LINKEDIN_POOL_FLOOR_RATIO` | `0.40` | Reserved share for verified non-LinkedIn sources |
| `ENABLE_SOURCE_REMOTIVE_SECURITY` | `true` | Remotive public security/contract API |
| `ENABLE_SOURCE_REMOTEOK_SECURITY` | `true` | RemoteOK public security/contract API |
| `ENABLE_SOURCE_WWR_SECURITY` | `true` | We Work Remotely public RSS feed |
| `ENABLE_SOURCE_ARBEITNOW_SECURITY` | `true` | Arbeitnow public remote security API |
| `ENABLE_LEGACY_MARKETPLACE_SOURCES` | `false` | Opt in to WAF-prone HTML marketplace diagnostics |
| `ENABLE_PROXY_POOL` | `false` | Opt in only for a verified proxy pool; public ATS APIs remain direct |
| `DAILY_SEND_HOURS` | `3` | Per-lane dedup window (matches 3h cron) |
| `GLOBAL_DEDUP_HOURS` | `3` | Cross-channel dedup window |
| `LLM_CLASSIFIER_ENABLED` | `true` | Enable Claude Haiku for borderline jobs |
| `ENABLE_SOURCE_EXPANDED` | `true` | AKM expanded aggregator sources |
| `ENABLE_SOURCE_TECH_BOARDS` | `true` | AKM tech-specific boards |
| `ENABLE_SOURCE_GULF_BOARDS` | `false` | Monster Gulf RSS (optional) |
| `ENABLE_SOURCE_LINKEDIN_API` | `false` | JSearch LinkedIn API (optional) |
| `ENABLE_SOURCE_LINKEDIN_HR_POSTS` | `false` | Disabled by default because DDG/SerpAPI paths are noisy |
| `DRY_RUN` | `false` | Fetch + score but don't send |
| `SEED_MODE` | `false` | Mark as seen without sending |

---

## Source Coverage

### Egypt (Highest Priority)
| Source | Method |
|--------|--------|
| LinkedIn — Egypt company pages | Guest API (gov + private sector) |
| LinkedIn — Egypt keyword search | Guest API (all governorates, Arabic + English) |
| LinkedIn — #Hiring posts (Egypt) | Guest API + hashtag keyword matching |
| Wuzzuf | HTML scrape |
| Wuzzuf RSS | Direct RSS |
| Bayt Egypt | JSON-LD public pages |
| EgyTech.fyi | Public jobs API |
| Mostaql | Arabic freelance platform |
| Khamsat | Arabic freelance platform |

### Gulf — KSA / UAE / Qatar / Kuwait / Bahrain / Oman
| Source | Method |
|--------|--------|
| LinkedIn — Gulf keyword search | Guest API |
| GulfTalent Direct | Public search endpoint |
| NaukriGulf Direct | Public AJAX search |
| Jobzella Gulf | JSON-LD public pages |
| Jina Scraper (Bayt + NaukriGulf + GulfTalent) | Jina.ai reader with nav-artifact filtering |
| Gulf Boards (Monster Gulf RSS) | RSS (optional) |

### Global / Remote
| Source | Method |
|--------|--------|
| Greenhouse (cybersec vendor APIs) | Direct API |
| Greenhouse Expanded (Big Tech + SaaS) | Direct API |
| AKM Expanded Sources | Aggregator bundle |
| AKM Tech Boards | Tech-specific boards |
| Cybersec Boards (Bugcrowd etc.) | Scrape |
| JSearch Enhanced via RapidAPI | RapidAPI |
| Telegram Channels | Telegram Bot API |
| Reddit / GitHub Hiring | RSS + scrape |
