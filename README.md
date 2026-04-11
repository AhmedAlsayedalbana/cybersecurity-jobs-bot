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
