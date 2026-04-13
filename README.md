# Cybersecurity Jobs Bot 

An automated job aggregator that continuously fetches cybersecurity job postings from 20+ sources across Egypt, the Gulf, and worldwide. It deduplicates, scores, and distributes jobs to a Telegram supergroup via topic-based channels.

Runs on GitHub Actions every **3 hours**.

---

## What It Does

1. **Fetches** jobs from 20+ active sources (LinkedIn, specialized boards, company career pages, #Hiring posts)
2. **Filters** for cybersecurity relevance using multi-layer keyword matching
3. **Deduplicates** by title+company and URL to prevent re-sending seen postings
4. **Scores and ranks** using a location-weighted and specialization-aware scoring model
5. **Routes** each job to the appropriate Telegram topic channel
6. **Sends** up to 10 unique jobs per channel per run — no cross-channel duplicates

---

## Scoring System

The scoring model prioritizes the **Egyptian job market first**, followed by Gulf, with targeted boosts for high-demand cybersecurity specializations.

| Factor | Points |
|---|---|
| 🇪🇬 Egypt location | **+10** |
| 🌙 Gulf location | **+8** |
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
| Posted today (< 24h) | +5 |
| Entry-level keywords | +3 |
| Experience: 0–2 years | +2 |
| Older than 7 days | -3 |

> **Specialization focus:** SOC, Penetration Testing, and Network Security receive the highest skill bonuses to reflect demand in the Egyptian and Gulf markets.

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
| 🇪🇬 Egypt Jobs | Location: Egypt |
| 🌙 Gulf Jobs | Location: Gulf (not Egypt) |
| 🌍 Remote Jobs | Remote (not Egypt or Gulf) |
| 🕵️ Penetration Testing / Red Team | Keywords in title/description |
| 🖥️ SOC & Threat Analysis | Keywords in title/description |
| 🛡️ Application Security | Keywords in title/description |
| ☁️ Cloud & Infrastructure Security | Keywords in title/description |
| 📋 GRC & Compliance | Keywords in title/description |
| ⚙️ Security Engineering | Keywords in title/description |
| 🎓 Internships & Entry Level | junior / intern / trainee / graduate |

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

## Deduplication

- **Within a run:** jobs deduped by `title+company` and URL before sending
- **Across runs:** seen IDs stored in `seen_jobs.json` with timestamps, expire after 7 days
- **Cross-channel:** each job sent to at most one channel per run

---

## Schedule

The bot runs every **3 hours** via GitHub Actions (`cron: '0 */3 * * *'`), plus supports manual dispatch from the Actions tab.

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
| `TOPIC_INTERNSHIPS` | Thread ID for Internships & Entry Level topic |
| `TOPIC_GULF` | Thread ID for Gulf Jobs topic |
| `SERPAPI_KEY` | (Optional) Google Jobs via SerpAPI |
| `RAPIDAPI_KEY` | (Optional) JSearch via RapidAPI |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | (Optional) Adzuna API |
| `FINDWORK_API_KEY` | (Optional) Findwork API |
| `JOOBLE_API_KEY` | (Optional) Jooble API |
| `REED_API_KEY` | (Optional) Reed API |
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
├── main.py                       # Pipeline: fetch → filter → dedup → score → send
├── models.py                     # Job dataclass, filter logic
├── scoring.py                    # Scoring & ranking (updated)
├── dedup.py                      # Seen-jobs deduplication
├── classifier.py                 # Location classifier (Egypt / Gulf / Other)
├── telegram_sender.py            # Message formatting & multi-topic sending
├── config.py                     # Channels, keywords, environment variables
├── sources/
│   ├── __init__.py
│   ├── linkedin.py               # LinkedIn jobs search
│   ├── linkedin_hiring.py        # LinkedIn #Hiring posts
│   ├── gov_egypt.py              # Egyptian government / ITIDA / EGCERT
│   ├── egypt_alt.py              # Wuzzuf + Egypt alt sources
│   ├── gov_gulf.py               # Gulf government + enterprise careers
│   ├── gulf_boards.py            # Gulf job boards
│   ├── cybersec_boards.py        # CyberSecJobs, Bugcrowd, HackerOne
│   ├── tech_boards.py            # BuiltIn + Big Tech Greenhouse boards
│   ├── remotive.py / himalayas.py / jobicy.py / remoteok.py
│   ├── arbeitnow.py / wwr.py / workingnomads.py
│   ├── freelance.py              # Mostaql, Khamsat, Truelancer
│   ├── google_jobs.py            # SerpAPI — Google Jobs
│   ├── adzuna.py / jooble.py / findwork.py / reed.py / jsearch.py
│   └── http_utils.py             # Shared HTTP helpers
└── .github/workflows/job_bot.yml # GitHub Actions — runs every 3 hours
```

---

## Recent Changes

| File | Change |
|---|---|
| `.github/workflows/job_bot.yml` | Schedule changed from every hour to **every 3 hours** |
| `scoring.py` | Egypt boosted to +10, Gulf to +8. SOC / Pentest / Network Security specializations elevated to **+5**. Network Security keywords added (Firewall, Palo Alto, Fortinet, Cisco, Zero Trust, IDS/IPS). |
| `README.md` | Updated to reflect all current scoring, schedule, and channel configuration |
