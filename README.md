# Cybersecurity Jobs Bot — Ultimate v50+

> **Definitive merge: AT v47 + AKM fix2 — the best of both worlds.**

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
| `LINKEDIN_TOTAL_BUDGET_SECONDS` | `180` | Hard cap for LinkedIn Unified |
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
