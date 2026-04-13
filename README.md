# Cybersecurity Jobs Bot

An automated job aggregator that fetches cybersecurity job postings from 15+ sources across Egypt, Gulf, and worldwide — deduplicates, scores, and distributes them to a Telegram group with topic-based channels.

Runs **every hour** via GitHub Actions.

---

## What It Does

1. **Fetches** jobs from 20+ active sources (LinkedIn, job boards, company pages, #Hiring posts)
2. **Filters** for cybersecurity relevance using multi-layer keyword matching
3. **Deduplicates** by title+company and URL to avoid re-sending seen jobs
4. **Scores and ranks** by location priority, recency, and role relevance
5. **Routes** each job to the appropriate Telegram topic channel
6. **Sends** up to 10 unique jobs per channel per run

---

## Schedule

| Trigger | Frequency |
|---|---|
| Automatic | Every hour (`0 * * * *`) |
| Manual | Via GitHub Actions → Run workflow |

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
| Bugcrowd Jobs | Greenhouse API |
| HackerOne Careers | JSON-LD scrape |
| BuiltIn | JSON-LD scrape |

### Big Tech (Security Roles Only)
Greenhouse API boards filtered for security titles: Google, Microsoft, Meta, Amazon, Apple, Netflix, Stripe, Datadog, Cloudflare, Fastly, Figma, MongoDB, and others.

### Remote Job Boards (Worldwide)
Remotive · Himalayas · Jobicy · RemoteOK · Arbeitnow · We Work Remotely · Working Nomads

### Freelance / Arab Platforms
Mostaql (مستقل) · Khamsat (خمسات) · Truelancer

### Optional (API Key Required)
Adzuna · Jooble · Findwork · Reed · Google Jobs (SerpAPI)

> **Removed dead sources:** GulfTalent (403) · Saudi Greenhouse slugs (404) · CyberSecJobs (404) · WorkInSecurity.co.uk (DNS failure)

---

## LinkedIn #Hiring Feature

LinkedIn members and companies post with `#Hiring` when they have open roles — often before or instead of a formal listing. The bot scrapes these posts for Egypt, Gulf, and Remote, then:

- **Matches** the raw text to a canonical cybersecurity job title (e.g. "hiring a soc analyst" → `SOC Analyst`)
- **Labels** the Telegram message as `LinkedIn #Hiring Post` so the reader knows it's a human lead
- Shows the **original posted title** alongside the canonical match

---

## Telegram Channels

Geo channels take priority over topic channels. Within geo channels no cross-channel duplicates. Topic channels are independent — a job can appear in multiple topic channels if it matches.

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
| 🎓 Entry Level & Internships | junior / intern / trainee / graduate |

---

## Message Format

```
[NEW]  Senior SOC Analyst

Posted as:  #Hiring — SOC Analyst        ← only for #Hiring posts
Company:    CrowdStrike
Location:   🇪🇬 Cairo, Egypt
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
- **Geo channels:** no cross-channel duplicates (egypt/gulf/remote)
- **Topic channels:** independent — same job can reach multiple topic channels

---

## Setup

### Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_GROUP_ID` | Telegram supergroup ID |
| `TOPIC_EGYPT` | Thread ID for Egypt Jobs topic |
| `TOPIC_GULF` | Thread ID for Gulf Jobs topic |
| `TOPIC_REMOTE` | Thread ID for Remote Jobs topic |
| `TOPIC_PENTEST` | Thread ID for Pentest topic |
| `TOPIC_SOC` | Thread ID for SOC topic |
| `TOPIC_APPSEC` | Thread ID for AppSec topic |
| `TOPIC_CLOUDSEC` | Thread ID for Cloud Security topic |
| `TOPIC_GRC` | Thread ID for GRC topic |
| `TOPIC_SECENG` | Thread ID for Security Engineering topic |
| `TOPIC_INTERNSHIPS` | Thread ID for Entry Level topic |
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
│   ├── linkedin.py
│   ├── linkedin_hiring.py    # LinkedIn #Hiring posts
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
