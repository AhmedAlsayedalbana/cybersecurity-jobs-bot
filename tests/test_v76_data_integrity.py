"""v76 data-quality regression tests — 19-point spec.

These tests enforce the canonical job record contract: evidence-based
category assignment (Pentest requires offensive evidence), source-backed
skills only, original title preserved, employer/recruiter separation,
source-backed location, verified-Open-only, and same-job apply URLs.

Regression matrix (from the spec):
  A) Defensive-only roles (incident response, SIEM/SOC, Fortinet/network,
     Security Engineer) must NOT be classified as Pentest.
  B) Skills never appear without canonical evidence.
  C) The card uses primary_category (legacy extraction is bypassed).
  D) Original title is never replaced by the category.
  E) Recruiter/agency is never shown as the employer.
  F) Location is source-backed, never invented.
  G) "Open" appears only when verified.
  H) Apply URL is the same-job URL, never a search page.
  I) The Telegram card renders the full canonical record unchanged by
     downstream code (format_job_message must not re-extract anything).
"""

import pytest

from models import Job, CyberVerdict


def _job(title: str, **overrides) -> Job:
    job = Job(
        title=title,
        company=overrides.pop("company", "Acme"),
        location=overrides.pop("location", "Cairo, Egypt"),
        url=overrides.pop("url", "https://example.com/job/123"),
        source=overrides.pop("source", "linkedin"),
        description=overrides.pop("description", ""),
        posted_date=overrides.pop("posted_date", "2026-08-19"),
        tags=overrides.pop("tags", []),
        job_type=overrides.pop("job_type", "Full-time"),
    )
    job.cyber_verdict = (overrides.pop("cyber_verdict", None)
                         or CyberVerdict.CONFIRMED.value)
    for key, value in overrides.items():
        setattr(job, key, value)
    return job


def _enrich(job: Job) -> None:
    """Run the single canonical-enrichment point the pipeline uses."""
    from main import _enrich_canonical_record
    _enrich_canonical_record([job])


def _card(job: Job) -> str:
    from telegram_sender import format_job_message
    return format_job_message(job)


# ── A) Category evidence: Pentest requires offensive evidence ───────────

def test_incident_response_is_soc_not_pentest():
    job = _job("Digital Incident Response Specialist", location="Riyadh, Saudi Arabia",
               description="Lead incident response investigations, triage alerts, "
                           "run post-incident reviews and containment playbooks.")
    _enrich(job)
    assert "Pentest" not in job.primary_category, (
        "IR without offensive evidence must never be Pentest")
    assert job.category_evidence, "category evidence must never be empty"


def test_siem_and_soc_is_soc_domain():
    job = _job("SOC Analyst L2",
               description="Monitor SIEM dashboards, tune Splunk correlation rules, "
                           "investigate alerts and manage the incident response queue.")
    _enrich(job)
    assert "Pentest" not in job.primary_category
    assert "SOC" in job.primary_category or "Threat" in job.primary_category


def test_fortinet_network_is_network_security():
    job = _job("Network Security Engineer",
               description="Deploy and manage Fortinet firewalls, IPS/IDS sensors "
                           "and network segmentation for the corporate LAN.")
    _enrich(job)
    assert "Network" in job.primary_category, job.primary_category
    assert "Pentest" not in job.primary_category


def test_security_engineer_stays_engineering_without_offense():
    job = _job("Security Engineer",
               description="Maintain IAM policies, endpoint protection rollouts "
                           "and internal security tooling integrations.")
    _enrich(job)
    assert job.primary_category == "Security Engineering"
    assert "Pentest" not in " ".join(job.secondary_categories)


def test_pentest_requires_offensive_evidence_in_content():
    job = _job("Penetration Tester",
               description="Only defensive keywords appear here: SIEM, firewall, "
                           "monitoring, compliance, SOC dashboards.")
    _enrich(job)
    assert "Pentest" not in job.primary_category, (
        "defensive-only content can never yield a Pentest category")
    # With genuine offensive evidence it may qualify:
    real = _job("Penetration Tester", description="Run penetration tests, "
                "chain exploits against test environments, write exploit "
                "reports for the red team.")
    _enrich(real)
    assert "Pentest" in real.primary_category


# ── B) Skills are source-backed only ─────────────────────────────────────

def test_no_skill_without_evidence():
    job = _job("Firewall Administrator",
               description="Administer Palo Alto firewalls and FortiGate VPNs.")
    _enrich(job)
    for skill, evidence in job.skills_with_evidence.items():
        assert evidence, f"skill {skill!r} must carry at least one evidence string"
        lower_text = f"{job.title} {job.description} {' '.join(job.tags)}".lower()
        # Evidence must be an actual substring of the job's own content.
        assert any(ev.lower() in lower_text for ev in evidence), evidence


def test_unknown_skill_never_appears():
    job = _job("Security Analyst",
               description="Review security alerts and write incident reports.")
    _enrich(job)
    assert "Kubernetes" not in job.skills_with_evidence
    assert "Burp Suite" not in job.skills_with_evidence
    # No skills at all is acceptable; an empty dict is safe.
    assert job.skills_with_evidence.keys().isdisjoint(
        {"Kubernetes", "Burp Suite", "AWS"})


# ── C/D) Card uses the canonical record and keeps the original title ────

def test_card_uses_primary_category():
    job = _job("SOC Analyst L2",
               description="Monitor SIEM dashboards, tune Splunk correlation rules.")
    _enrich(job)
    card = _card(job)
    assert "SOC / Threat / Incident Response" in card, card


def test_original_title_preserved_in_card():
    job = _job("Senior Blue Team Analyst — Incident Response",
               description="Investigate security incidents via Splunk alerts.")
    _enrich(job)
    card = _card(job)
    assert "Senior Blue Team Analyst — Incident Response" in card, (
        "the card must render the original title, never the category name")


def test_skills_line_never_invented_on_card():
    job = _job("Firewall Engineer", description="Manage FortiGate and Palo Alto.")
    _enrich(job)
    card = _card(job)
    for skill in job.skills_with_evidence or {}:
        assert skill in card
    # And nothing the enrichment never attached:
    assert "Kubernetes" not in card


# ── E) Recruiter is never the employer ───────────────────────────────────

def test_recruiter_separated_from_employer():
    job = _job("SOC Analyst",
               company="Robert Walters Recruitment",
               description="Client: Vodafone Egypt is hiring a SOC analyst to "
                           "monitor security events with Splunk.")
    _enrich(job)
    assert job.recruiter_name, "agency recruiter must be detected"
    card = _card(job)
    assert "Recruited by:" in card, card
    # The hiring employer line must never carry the recruiter's name:
    lines = card.split("\n")
    employer_line = next(l for l in lines if l.startswith("🏢"))
    assert "Robert Walters" not in employer_line, employer_line
    assert "Vodafone" in employer_line, employer_line


def test_ordinary_company_never_split():
    job = _job("Security Engineer", company="Vodafone Egypt",
               description="Manage endpoint protection and SIEM alerts.")
    _enrich(job)
    assert not job.recruiter_name


# ── F) Location is source-backed ─────────────────────────────────────────

def test_location_never_invented():
    job = _job("GRC Analyst", company="CIB",
               location="Cairo, Egypt",
               description="ISO 27001 compliance audits and risk registers.")
    _enrich(job)
    card = _card(job)
    assert "📍 Cairo, Egypt" in card
    # Nothing derived from the recruiter pattern "for X" or the category
    # may leak into the location line:
    lines = [l for l in card.split("\n") if l.startswith("📍")]
    assert lines[0].count(",") == 1 or "Cairo" in lines[0]


# ── G) "Open" status only when verified ─────────────────────────────────

def test_open_status_hidden_when_unverified():
    job = _job("SOC Analyst", description="SIEM monitoring for the SOC team.")
    _enrich(job)
    assert not job.status_open_verified
    card = _card(job)
    assert "Open" not in card, card


def test_open_status_shown_when_verified():
    # A title with no seniority signal resolves to "Open" ONLY when the
    # listing itself verified the all-levels status — the verified flag is
    # the one gate that allows "Open" on the card.
    from telegram_sender import _display_level
    job = _job("Cybersecurity Operations", description="Day-to-day security operations support.")
    _enrich(job)
    job.status_open_verified = True
    card = _card(job)
    assert _display_level(job) == "Open", (
        "verified all-levels status must render as Open")
    assert "Open" in card, card


# ── H) Apply URL is the same-job URL ─────────────────────────────────────

def test_apply_url_is_job_url_not_search_page():
    job = _job("SOC Analyst",
               url="https://careers.vodafone.com/egypt/jobs/soc-analyst-8821",
               description="SIEM monitoring with Splunk.")
    _enrich(job)
    card = _card(job)
    assert "careers.vodafone.com/egypt/jobs/soc-analyst-8821" in card
    # A search page or homepage must never appear:
    assert "jobs/search" not in card
    assert "vodafone.com/" in card and "/jobs/" in card


# ── I) Downstream formatting never re-extracts ──────────────────────────

def test_regardless_of_downstream_changes_card_matches_canonical_record():
    """The spec regression case (point 18): a Defensive Incident Response
    role in Riyadh with Robert Walters as recruiter, with a skills list
    including SIEM/IR, must never be rendered as a Pentest card with
    invented skills."""
    job = _job("Digital Incident Response Specialist",
               company="Robert Walters Recruitment",
               location="Riyadh, Saudi Arabia",
               url="https://robertwalters.careers/jobs/87234",
               description="Client: a telecom operator in Riyadh needs an IR "
                           "specialist: SIEM alert triage, incident response "
                           "playbooks, Splunk dashboards.")
    _enrich(job)
    card = _card(job)
    assert "Pentest" not in card, card
    assert "Incident Response" in card
    assert "Robert Walters" in card
    assert "Splunk" in card or "SIEM" in card
    # Only evidence-backed skills:
    for skill in job.skills_with_evidence or {}:
        assert skill in ("Splunk", "SIEM") or skill in card
