# Ultimate v50+ — AT + AKM Definitive Merge

## Summary

This is the definitive merge of AT v47 (stability, modularity, Arabic geo) and
AKM fix2 (4-layer AI filter, advanced scoring, broader tests).
Every file has been carefully selected or merged for maximum quality.

## File-by-file decisions

| File | Source | Reason |
|------|--------|--------|
| `ai_filter.py` | Merged (MCL base + MCO fallback) | Full 4-layer + intelligence offline fallback |
| `main.py` | MCL + MCO `_is_stale_job` | MCL imports `ai_filter` + `diversity_rerank` |
| `config.py` | MCO + MCL LLM flag | 7d freshness, 3h dedup, LLM enabled by default |
| `scoring.py` | MCL | Cleaner imports, no `job_intelligence` dependency |
| `intelligence/geo.py` | MCO | Arabic frozenset for Egypt cities |
| `intelligence/patterns.py` | MCO | 305 lines vs MCL's 289 — more patterns |
| `intelligence/dedupe.py` | MCO | 137 lines vs MCL's 129 — more robust |
| `source_registry.py` | Merged | MCO's sources + MCL's tier architecture |
| `tests/` | All 5 MCL files | Superset: includes test_ai_filter + test_scoring_advanced |
| `ml_models/` | MCO only | MCL has no ML model file |
| `.github/workflows/` | Merged | MCL's dry_run + MCO's env vars + source toggles |
| `README.md` | Merged | MCL's architecture diagram + MCO's source table |

## Key configuration values

- `MAX_JOB_AGE_DAYS = 7` — Bayesian decay handles 5–7d penalty range
- `DAILY_SEND_HOURS = 3` — exactly matches cron every-3h interval
- `GLOBAL_DEDUP_HOURS = 3` — prevents re-send within same window
- `LLM_CLASSIFIER_ENABLED = True` — Claude Haiku active when API key present
- `MAX_JOBS_PER_CHANNEL = 10` — raised from 5 for higher throughput

## What was deliberately NOT merged

- `MERGE_NOTES.md` / `UPGRADE_NOTES_AKM.md` from MCO — superseded by this file
- `mco/ai_filter.py` compatibility wrapper — superseded by full implementation
- MCL `config.py` 2-day freshness window — too strict, misses quality older jobs
- MCL `config.py` 5h dedup window — doesn't match 3h cron schedule
