# Cybersecurity Jobs Bot

An automated job aggregator that fetches cybersecurity job postings from 15+ sources across Egypt, Gulf, and worldwide — deduplicates, scores, and distributes them to a Telegram group with topic-based channels.

Runs on a daily schedule via GitHub Actions.

---

## What It Does

1. **Fetches** jobs from 20+ active sources (LinkedIn, job boards, company pages, #Hiring posts)
2. **Filters** for cybersecurity relevance using multi-layer keyword matching
3. **Deduplicates** by title+company and URL to avoid re-sending seen jobs
4. **Scores and ranks** by location priority, recency, and role relevance
5. **Routes** each job to the appropriate Telegram topic channel
6. **Sends** up to 10 unique jobs per channel per run — no cross-channel duplicates

---

## Job Sources

### Egypt (Highest Priority)
| Source | Method |
|---|---|
| LinkedIn — Egypt company pages | Guest API (gov + private sector) |
| LinkedIn — Egypt keyword search | Guest API (all governorates) |
| LinkedIn — #Hiring posts (Egypt) | Guest API + hashtag keyword matching |
| Wuzzuf | HTML scrape |

### Gulf — KSA / UAE / Qatar / Kuwait / Bahrain / Oman
| Source | Method |
|---|---|
| STC KSA | Careers page scrape |
| TDRA UAE | Careers page scrape |
| Etisalat UAE | Careers page scrape |
| LinkedIn — Gulf company pages | Guest API |
| LinkedIn — Gulf keyword search | Guest API |
| LinkedIn — #Hiring posts (Gulf) | Guest API + hashtag keyword matching |
| Monster Gulf | RSS feed |

### Cybersecurity-Specific Boards
| Source | Method |
|---|---|
| CyberSecJobs.com | HTML scrape |
| Bugcrowd Jobs | Careers page |
| HackerOne Careers | JSON-LD scrape |
| BuiltIn | API |

### Big Tech (Security Roles Only)
Greenhouse API boards filtered for security titles: Google, Microsoft, Meta, Amazon, Apple, Netflix, Stripe, Datadog, Cloudflare, Fastly, Figma, MongoDB, and others.

### Remote Job Boards (Worldwide)
Remotive · Himalayas · Jobicy · RemoteOK · Arbeitnow · We Work Remotely · Working Nomads

### Freelance / Arab Platforms
Mostaql (مستقل) · Khamsat (خمسات) · Truelancer · WorkInSecurity.co.uk

### Optional (API Key Required)
Adzuna · Jooble · Findwork · Reed · Google Jobs (SerpAPI)

---

## LinkedIn #Hiring Feature

LinkedIn members and companies post with `#Hiring` when they have open roles — often before or instead of a formal listing. The bot scrapes these posts for Egypt, Gulf, and Remote, then:

- **Matches** the raw text to a canonical cybersecurity job title (e.g. "hiring a soc analyst" → `SOC Analyst`)
- **Labels** the Telegram message as `LinkedIn #Hiring Post` so the reader knows it's a human lead
- Shows the **original posted title** alongside the canonical match

---

## Telegram Channels

Each job is routed to exactly **one** Telegram topic channel. No job appears in more than one channel. Geo channels take priority over topic channels.

| Channel | Match Logic |
|---|---|
| Egypt Jobs | Location: Egypt |
| Gulf Jobs | Location: Gulf (not Egypt) |
| Remote Jobs | Remote (not Egypt or Gulf) |
| Penetration Testing / Red Team | Keywords in title/description |
| SOC & Threat Analysis | Keywords in title/description |
| Application Security | Keywords in title/description |
| Cloud & Infrastructure Security | Keywords in title/description |
| GRC & Compliance | Keywords in title/description |
| Security Engineering | Keywords in title/description |
| Entry Level | junior / intern / trainee / graduate |

---

## Message Format

```
[NEW]  Senior SOC Analyst

Posted as:  #Hiring — SOC Analyst        ← only for #Hiring posts
Company:    CrowdStrike
Location:   Egypt (Cairo)
Domain:     SOC / Blue Team
Level:      Senior
Skills:     SIEM, Splunk, Threat Intel, IR
Relevance:  High Priority
Type:       Full-time
Via:        LinkedIn #Hiring Post

Apply Now
```

---

## Scoring System

| Factor | Points |
|---|---|
| Egypt location | +8 |
| Gulf location | +6 |
| Remote | +5 |
| Hybrid (Remote + Egypt/Gulf) | +2 bonus |
| SIEM / Splunk / QRadar | +4 each |
| Cloud Security / AWS / Azure | +4 each |
| SOC / Pentest / Vulnerability | +3 each |
| Posted today (< 24h) | +5 |
| Entry-level keywords | +3 |
| Older than 7 days | -3 |

---

## Deduplication

- **Within a run:** jobs deduped by `title+company` and URL before sending
- **Across runs:** seen IDs stored in `seen_jobs.json` with timestamps, expire after 7 days
- **Cross-channel:** each job sent to at most one channel per run

---

## Setup

### Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_GROUP_ID` | Telegram supergroup ID |
| `TOPIC_EGYPT` | Thread ID for Egypt Jobs topic |
| `TOPIC_REMOTE` | Thread ID for Remote Jobs topic |
| `TOPIC_PENTEST` | Thread ID for Pentest topic |
| `TOPIC_SOC` | Thread ID for SOC topic |
| `TOPIC_APPSEC` | Thread ID for AppSec topic |
| `TOPIC_CLOUDSEC` | Thread ID for Cloud Security topic |
| `TOPIC_GRC` | Thread ID for GRC topic |
| `TOPIC_SECENG` | Thread ID for Security Engineering topic |
| `TOPIC_ENTRY` | Thread ID for Entry Level topic |
| `SERPAPI_KEY` | (Optional) Google Jobs via SerpAPI |
| `SEED_MODE` | Set `1` on first run to populate seen list without sending |

### First Run (Seed Mode)

```bash
SEED_MODE=1 python main.py
```

### Normal Run

```bash
python main.py
```

---

## File Structure

```
├── main.py
├── models.py
├── scoring.py
├── dedup.py
├── classifier.py
├── telegram_sender.py
├── config.py
├── sources/
│   ├── __init__.py
│   ├── linkedin.py           # LinkedIn jobs search
│   ├── linkedin_hiring.py    # LinkedIn #Hiring posts  ← NEW
│   ├── gov_egypt.py
│   ├── egypt_alt.py
│   ├── gov_gulf.py
│   ├── gulf_boards.py
│   ├── cybersec_boards.py
│   ├── tech_boards.py
│   ├── remotive.py / himalayas.py / jobicy.py / remoteok.py
│   ├── arbeitnow.py / wwr.py / workingnomads.py
│   ├── freelance.py
│   ├── google_jobs.py / adzuna.py / jooble.py / findwork.py / reed.py
│   └── http_utils.py
└── .github/workflows/job_bot.yml
```
# 🔐 Cybersecurity Jobs Bot v3

Telegram bot that automatically fetches, filters, scores, and sends **Cybersecurity jobs only** to a Telegram supergroup with topic channels.

**Priority order:** 🇪🇬 Egypt → 🌍 Remote → 🌙 Gulf (KSA/UAE/Kuwait)

---

## 📁 Project Structure

```
cybersec-bot/
├── main.py               # Entry point — orchestrates the full pipeline
├── config.py             # All configuration: keywords, geo, topics, scoring weights
├── models.py             # Job dataclass + filtering logic (cybersec + geo)
├── scoring.py            # Scoring & ranking system (Egypt-first priority)
├── telegram_sender.py    # Message formatting + multi-topic routing
├── dedup.py              # Seen-job deduplication (seen_jobs.json)
├── sources/
│   ├── __init__.py       # Source registry (ALL_FETCHERS list)
│   ├── cybersec_boards.py  # InfoSec-Jobs, CyberSecJobs, ISACA, ISC2, SecurityJobs
│   ├── tech_boards.py      # Dice, HackerOne, Bugcrowd, Greenhouse, Lever
│   ├── remotive.py       # Remotive remote jobs
│   ├── himalayas.py      # Himalayas remote jobs
│   ├── jobicy.py         # Jobicy remote jobs
│   ├── remoteok.py       # RemoteOK remote jobs
│   ├── arbeitnow.py      # Arbeitnow
│   ├── wwr.py            # We Work Remotely
│   ├── workingnomads.py  # Working Nomads
│   ├── linkedin.py       # LinkedIn (Egypt + Gulf + Remote)
│   ├── adzuna.py         # Adzuna API (optional key)
│   ├── findwork.py       # Findwork API (optional key)
│   ├── jooble.py         # Jooble API (optional key)
│   ├── reed.py           # Reed API (optional key)
│   ├── jsearch.py        # JSearch via RapidAPI (optional key)
│   ├── freelance.py      # Upwork, Freelancer, Khamsat (خمسات), Mustaqil (مستقل)
│   └── http_utils.py     # Shared HTTP session helpers
├── .github/workflows/
│   └── job_bot.yml       # GitHub Actions — runs 4x daily
└── requirements.txt
```

---

## 🚀 Setup Guide

### 1. Fork / Clone this repo to GitHub

### 2. Create your Telegram Bot
1. Message `@BotFather` → `/newbot`
2. Add the bot to your supergroup
3. Make the bot an **Admin** (needs "Post Messages" permission)
4. Enable **Topics** in your supergroup settings
5. Get the **thread IDs** for each topic (see below)

### 3. Get Thread IDs for Topics
Send a message in each topic, then check the URL or use:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Look for `message_thread_id` in the response.

### 4. Set GitHub Secrets
Go to **Settings → Secrets → Actions** and add:

| Secret | Required | Description |
|--------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ | Your bot token from BotFather |
| `TELEGRAM_GROUP_ID` | ✅ | Your supergroup ID (negative number, e.g. `-1001234567890`) |
| `TOPIC_GENERAL` | ✅ | Thread ID for "All Cybersecurity Jobs" topic |
| `TOPIC_EGYPT` | ✅ | Thread ID for Egypt jobs topic |
| `TOPIC_REMOTE` | ⬜ | Thread ID for Remote jobs topic |
| `TOPIC_PENTEST` | ⬜ | Thread ID for Pentest topic |
| `TOPIC_SOC` | ⬜ | Thread ID for SOC topic |
| `TOPIC_APPSEC` | ⬜ | Thread ID for AppSec topic |
| `TOPIC_CLOUDSEC` | ⬜ | Thread ID for Cloud Security topic |
| `TOPIC_GRC` | ⬜ | Thread ID for GRC topic |
| `TOPIC_SECENG` | ⬜ | Thread ID for Security Engineering topic |
| `TOPIC_GULF` | ⬜ | Thread ID for Gulf jobs (KSA/UAE/Kuwait) |
| `TOPIC_INTERNSHIPS` | ⬜ | Thread ID for Internships topic |
| `RAPIDAPI_KEY` | ⬜ | RapidAPI key (for JSearch) |
| `ADZUNA_APP_ID` | ⬜ | Adzuna App ID |
| `ADZUNA_APP_KEY` | ⬜ | Adzuna App Key |
| `JOOBLE_API_KEY` | ⬜ | Jooble API key |
| `FINDWORK_API_KEY` | ⬜ | Findwork API key |
| `REED_API_KEY` | ⬜ | Reed API key |

> **Note:** Only `TELEGRAM_BOT_TOKEN`, `TELEGRAM_GROUP_ID`, and `TOPIC_GENERAL` are strictly required. All others are optional enhancements.

### 5. Create the `data` branch (for seen_jobs persistence)
```bash
git checkout --orphan data
git rm -rf .
echo '[]' > seen_jobs.json
git add seen_jobs.json
git commit -m "init data branch"
git push origin data
git checkout main
```

### 6. First Run — Seed Mode
On the first run (empty `seen_jobs.json`), the bot automatically enters **Seed Mode**:
- Fetches all current jobs
- Marks them all as **seen** (no messages sent)
- Next run will only send NEW jobs

To force seed mode manually, add `SEED_MODE=1` to the workflow env.

---

## ⚙️ How It Works

```
Every 6 hours:
  1. Fetch jobs from 15+ sources
  2. Filter: must match cybersec keywords + geo rules
  3. Deduplicate: skip already-seen jobs
  4. Score & rank:
       Egypt onsite  → +8 pts  🇪🇬
       Remote        → +4 pts  🌍
       Gulf          → +2 pts  🌙
       Pentest/SOC   → +9-10 pts
       Prestige co.  → +3 pts
  5. Send top 15 jobs to matching Telegram topics
  6. Save seen_jobs.json to `data` branch
```

---

## 🎯 Scoring System

| Factor | Points |
|--------|--------|
| Egypt onsite 🇪🇬 | +8 |
| Remote 🌍 | +4 |
| Gulf 🌙 | +2 |
| Pentest / Red Team title | +10 |
| SOC Analyst / Malware / DFIR | +9 |
| Cloud Security / AppSec | +9 |
| Security Engineer / Architect | +8-9 |
| GRC / Compliance | +7-8 |
| Security Analyst (generic) | +7 |
| Senior / Lead / Principal | +2-3 |
| Director / Head of | +3 |
| CISO | +5 |
| Junior | -1 |
| Intern | -2 |
| Trusted source (HackerOne, Bugcrowd) | +3 |
| Prestige company | +3 |

---

## 🔧 Customization

- **Add more companies to Greenhouse/Lever:** Edit `GREENHOUSE_COMPANIES` / `LEVER_COMPANIES` in `tech_boards.py`
- **Adjust scoring weights:** Edit `scoring.py`
- **Add/remove topic channels:** Edit `CHANNELS` in `config.py` + workflow secrets
- **Change send frequency:** Edit `cron` in `.github/workflows/job_bot.yml`
- **Change max jobs per run:** Edit `MAX_JOBS_PER_RUN` in `config.py` (default: 15)

---

## 🛟 Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot not sending | Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_GROUP_ID` secrets |
| Topics not working | Verify thread IDs in secrets; bot must be admin |
| Too many/few jobs | Adjust `MAX_JOBS_PER_RUN` or `min_score` in `main.py` |
| LinkedIn blocked | LinkedIn may rate-limit; this is non-fatal — other sources still work |
| Duplicate jobs | Let the bot run; `seen_jobs.json` on `data` branch prevents re-sends |
