# v56 — Merge of `_final` (v55) and `-v54_1` branches

Base: `cybersecurity-jobs-bot_final.zip` (v55) — kept as-is because it had the
safer architecture (idempotent Telegram outbox, DRY_RUN, STRICT_PUBLIC_ONLY,
per-source attempt tracking, human-verified-only ML retraining, unified
`marketplace_sources.py`).

## What was pulled in from `-v54_1` and why

1. **Rotating-proxy pool** (`sources/http_utils.py`)
   Ported `_ProxyPool` (health scoring, banning/cooldowns, per-domain
   stickiness) from v54 into v55's simpler, safer request pipeline. Fully
   opt-in: if the `PROXIES` env var is empty, behaviour is byte-for-byte the
   old direct-only v55 flow. `get_proxy_status()` now feeds the health
   report and `database.save_proxy_stats()` (that DB method already existed
   in v55, it just wasn't being called).

2. **`use_proxy=False` override** replaces v54's pattern of a second,
   unmonitored `requests.Session()` inside `sources/regional_boards.py`
   (which bypassed all retry/rate-limit/metrics logic). Same intended
   effect — force a direct connection for boards that reject proxied
   traffic — but it now goes through the shared, monitored client.

3. **Automatic (non-authoritative) ML training-sample collection** in
   `main.py`, gated by the new `ENABLE_TRAINING_DATA_COLLECTION` flag and
   skipped entirely during `DRY_RUN`. This writes `label_source="automatic"`
   rows only. `ml_filter.maybe_retrain_from_db()` was already hard-coded in
   v55 to read *only* `label_source="human_verified"` rows, so this addition
   cannot itself bias or trigger a retrain — it just builds a dataset a
   human can later promote.

4. **Wazzif (وظف) board** registered as its own source
   (`sources/egypt_boards.py::fetch_wazzif`). This is the one genuinely new,
   non-duplicate connector found in the v54 registry — everything else v54
   registered under separate keys (`bayt_egypt`, `wuzzuf_priority`,
   `wuzzuf_rss`, `akhtaboot_egypt`, `gulftalent_api`, `jina_boards`,
   `upwork`, `freelancer`, `mostaql`, `khamsat`, `fiverr`) turned out to
   already be covered — with a cleaner direct→Reader-fallback implementation
   and honest policy reporting for restricted platforms — by v55's
   `sources/marketplace_sources.py`, or by `sources/mena_boards.py` (already
   present in both trees, just deliberately left disabled to avoid
   double-fetching the same boards). Re-registering those would have
   reintroduced duplicate postings, so they were **not** added.

## What was intentionally left out of v54

- The stale `claude-3-5-haiku-latest` LLM classifier reference — v55 already
  uses the current model.
- `ENABLE_SOURCE_MENA_BOARDS=True` default — kept `False` as in v55 to avoid
  double-fetching Akhtaboot/DrJobPro/Forasna/Tanqeeb against
  `marketplace_sources.py`.
- Unmonitored raw `requests` sessions bypassing the shared retry/metrics
  layer.
- CRLF line endings — normalised, this file tree is LF-only.
- A committed `jobs_bot.db` binary — removed; `.gitignore` already excludes
  it, this was a stray local artifact.

## Net result

- 28 sources registered, zero duplicate source keys.
- Proxy pool verified working (selection, banning, score recovery) both with
  and without `PROXIES` set.
- `db.save_proxy_stats()` / `db.record_training_sample()` verified wired up
  and the human-verified gate confirmed to hold.
- Full existing test suite passes unmodified: `177 passed, 5 skipped`.
