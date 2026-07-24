from types import SimpleNamespace
from datetime import datetime, timedelta

from sources import public_remote_feeds as feeds
from models import Job


def test_remotive_security_api_keeps_verified_contract_job(monkeypatch):
    monkeypatch.setattr(
        feeds,
        "get_json",
        lambda *_a, **_k: {
            "jobs": [{
                "title": "Senior Application Security Engineer (Contract)",
                "company_name": "Acme Security",
                "candidate_required_location": "Anywhere",
                "url": "https://remotive.com/remote-jobs/security/acme-1",
                "publication_date": "2026-07-24T08:00:00Z",
                "description": "Lead AppSec reviews and secure SDLC work.",
                "category": "devops-sysadmin",
                "job_type": "contract",
            }]
        },
    )

    result = feeds.fetch_remotive_security()

    assert result.status == "success"
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.source_key == "remotive_security"
    assert job.job_type == "Contract / Freelance"
    assert job.posted_date is not None
    assert job.extraction_method == "public_api_or_rss"
    assert job.provenance_hash


def test_remoteok_epoch_date_is_normalized(monkeypatch):
    monkeypatch.setattr(
        feeds,
        "get_json",
        lambda *_a, **_k: [
            {"legal": "RemoteOK public API"},
            {
                "id": "123",
                "position": "SOC Analyst",
                "company": "Example Co",
                "location": "Worldwide",
                "url": "/remote-jobs/123-soc-analyst",
                "epoch": 1784880000,
                "tags": ["security", "contract"],
                "description": "Monitor SIEM alerts and investigate incidents.",
            },
        ],
    )

    result = feeds.fetch_remoteok_security()

    assert result.status == "success"
    job = result.jobs[0]
    assert job.url == "https://remoteok.com/remote-jobs/123-soc-analyst"
    assert job.posted_date.year == 2026
    assert job.job_type == "Contract / Freelance"


def test_wwr_rss_requires_date_and_security_intent(monkeypatch):
    rss = """<?xml version='1.0'?>
    <rss><channel><item>
      <title>Acme: Cloud Security Engineer - Contract</title>
      <link>https://weworkremotely.com/remote-jobs/acme-cloud-security</link>
      <pubDate>Fri, 24 Jul 2026 10:00:00 +0000</pubDate>
      <description>Design cloud security controls and threat detection.</description>
      <category>DevOps</category>
    </item></channel></rss>"""
    monkeypatch.setattr(
        feeds,
        "get_text_result",
        lambda *_a, **_k: SimpleNamespace(text=rss),
    )

    result = feeds.fetch_wwr_security()

    assert result.status == "success"
    assert result.jobs[0].title == "Cloud Security Engineer - Contract"
    assert result.jobs[0].company == "Acme"
    assert result.jobs[0].job_type == "Contract / Freelance"


def test_registry_uses_public_feeds_and_excludes_service_only_marketplaces():
    from sources.source_registry import get_source_specs

    keys = {spec.key for spec in get_source_specs()}
    assert {"remotive_security", "remoteok_security", "wwr_security", "arbeitnow_security"} <= keys
    assert not {"fiverr", "khamsat", "toptal"} & keys
    assert "upwork" not in keys


def test_telegram_enforces_60_40_on_actual_deliveries(monkeypatch):
    """Channel routing may duplicate jobs, so pool-only enforcement is insufficient."""
    import telegram_sender as sender

    class _Db:
        def was_sent_to_channel_recently(self, **_kwargs):
            return False

    monkeypatch.setattr(sender, "get_topic_thread_id", lambda _key: 1)
    monkeypatch.setattr(sender, "get_db", lambda: _Db())
    monkeypatch.setattr(sender, "_drain_retry_queue", lambda _db: 0)
    monkeypatch.setattr(sender, "_send_to_topic", lambda *_a, **_k: True)
    monkeypatch.setattr(sender.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(sender, "MAX_JOBS_PER_CHANNEL", 10)

    posted = datetime.now() - timedelta(hours=1)
    jobs = [
        Job(
            f"SOC Analyst LI {index}", "LinkedIn", "Remote",
            f"https://www.linkedin.com/jobs/view/{900000000 + index}",
            "linkedin_unified",
            description="SIEM monitoring and incident response.",
            posted_date=posted,
        )
        for index in range(8)
    ] + [
        Job(
            f"SOC Analyst API {index}", "Remote Feed", "Remote",
            f"https://example.com/security/{index}", "remoteok_security",
            description="SIEM monitoring and incident response.",
            posted_date=posted,
        )
        for index in range(4)
    ]

    total, records = sender.send_jobs(jobs)
    linkedin = sum(
        "linkedin" in (getattr(job, "source_key", "") or job.source).lower()
        for job, *_rest in records
    )

    assert total == len(records)
    assert linkedin / total <= 0.60
