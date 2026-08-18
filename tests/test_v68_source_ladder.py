"""v68 regression tests — per-source fallback ladder, employer-context
evidence enrichment, and HR Posts final discovery/verification fix.

These tests are hermetic (no real network): they monkeypatch the transport
functions and verify the contracts the v68 implementation adds on top of
the v62-v67 guarantees.
"""

from __future__ import annotations

import time
from unittest import mock

from models import Job, CyberVerdict


# ============================================================
# official_careers.py — fallback ladder
# ============================================================

def _make_source(**overrides):
    from sources.official_careers import SOURCES_BY_KEY
    return SOURCES_BY_KEY[overrides.get("key", "fabmisr")]


class TestV68FallbackLadder:
    """Per-source ladder: direct endpoint -> embedded JSON -> Jina reader -> Playwright."""

    def test_jina_fallback_succeeds_when_direct_returns_nothing(self):
        """When the direct endpoint parses structure but finds no jobs and the
        source has public_fallback, the Jina reader step rescues listings and
        returns transport='jina' WITHOUT touching Playwright."""
        from sources import official_careers as oc

        source = _make_source(key="aaib")
        assert source.public_fallback, "v68: failing AAIB must carry public_fallback"

        empty_outcome = oc._Outcome([], parsed=True)  # parsed but no jobs

        rescued_jobs = [
            Job(title="SOC Analyst", company="AAIB", location="Cairo, Egypt",
                url="https://aaib.com.eg/job/1", description="SIEM monitoring",
                source="aaib", source_key="aaib", provenance_hash="p1"),
        ]
        reader_outcome = oc._Outcome(rescued_jobs, parsed=True)

        with mock.patch.object(oc, "_fetch_direct", return_value=empty_outcome), \
             mock.patch.object(oc, "_fetch_via_public_reader", return_value=reader_outcome), \
             mock.patch.object(oc, "_fetch_with_browser") as browser:
            result = oc.fetch_source("aaib")

        assert result.status == "success"
        assert result.transport == "jina"
        assert result.jobs == rescued_jobs
        browser.assert_not_called()  # Playwright never touched

    def test_embedded_json_extraction_before_jina(self):
        """If the first page kept its raw HTML with embedded structured data,
        _jobs_from_html re-extraction is attempted BEFORE the Jina reader."""
        from sources import official_careers as oc

        source = _make_source(key="banque_misr")
        assert source.public_fallback

        html_with_ldjson = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"IT Security Engineer","hiringOrganization":{"name":"Banque Misr"}}'
            "</script>"
        )
        outcome = oc._Outcome([], parsed=True, raw_html=html_with_ldjson)

        extracted = [
            Job(title="IT Security Engineer", company="Banque Misr",
                location="Cairo, Egypt", url="https://banquemisr.com/job/7",
                description="SIEM monitoring", source="banque_misr",
                source_key="banque_misr", provenance_hash="p2"),
        ]

        with mock.patch.object(oc, "_fetch_direct", return_value=outcome), \
             mock.patch.object(oc, "_jobs_from_html", return_value=(extracted, True)) as jfh, \
             mock.patch.object(oc, "_fetch_via_public_reader") as reader:
            result = oc.fetch_source("banque_misr")

        assert jfh.called
        assert result.status == "success"
        assert result.transport == "embedded_json"
        reader.assert_not_called()  # Jina never attempted after a successful extraction

    def test_playwright_only_after_both_cheap_steps_fail(self):
        """A JS-only source whose endpoint, embedded extraction, and Jina
        reader all come back empty finally reaches the browser step."""
        from sources import official_careers as oc

        source = _make_source(key="nbe")
        assert source.public_fallback

        empty = oc._Outcome([], parsed=False)

        with mock.patch.object(oc, "_fetch_direct", return_value=empty), \
             mock.patch.object(oc, "_fetch_via_public_reader", return_value=empty), \
             mock.patch.object(oc, "_fetch_with_browser") as browser:
            browser.return_value = oc._Outcome([], parsed=False)
            oc.fetch_source("nbe")

        browser.assert_called_once()

    def test_public_fallback_disabled_for_healthy_sources(self):
        """Sources that never showed a blocked/timeout pattern (Forasna,
        Shaghalni, Vodafone) do NOT carry the rescue step — no added latency
        on healthy transports."""
        from sources import official_careers as oc

        for key in ("forasna", "shaghalni", "vodafone_egypt"):
            assert not oc.SOURCES_BY_KEY[key].public_fallback, (
                f"healthy source {key} must not pay a public-reader step"
            )

    def test_reader_failure_never_blocks_source(self):
        """A Jina reader failure reports honestly (status != success) and
        escalates to the browser step for JS-only sources instead of crashing."""
        from sources import official_careers as oc

        source = _make_source(key="cib_egypt")
        outcome = oc._Outcome([], parsed=False)

        with mock.patch.object(oc, "_fetch_direct", return_value=outcome), \
             mock.patch.object(oc, "_fetch_via_public_reader", return_value=oc._Outcome([], error_code="jina_unavailable")), \
             mock.patch.object(oc, "_fetch_with_browser") as browser:
            browser.return_value = oc._Outcome([], parsed=False)
            result = oc.fetch_source("cib_egypt")

        assert result.status in ("blocked", "empty")
        browser.assert_called_once()

    def test_reader_too_large_response_is_declined(self):
        """An oversized reader response is treated as noise — honest empty,
        never parsed, never escalated to the browser on non-JS-only sources."""
        from sources import official_careers as oc

        source = _make_source(key="hsbc_egypt")
        outcome = oc._Outcome([], parsed=False, raw_html="<p>nothing useful</p>")

        with mock.patch.object(oc, "_fetch_direct", return_value=outcome), \
             mock.patch.object(oc, "_fetch_via_public_reader", return_value=oc._Outcome([], parsed=False, error_code="jina_too_large")), \
             mock.patch.object(oc, "_fetch_with_browser") as browser:
            result = oc.fetch_source("hsbc_egypt")

        assert result.status == "blocked"
        browser.assert_not_called()  # HSBC is not a JS-only source

    def test_source_catalog_size_stable(self):
        """v68 does not add dozens of sources — the catalog stays the same
        size it was at v67 (registry changes were field-level only)."""
        from sources.official_careers import OFFICIAL_SOURCES
        assert 70 <= len(OFFICIAL_SOURCES) <= 80, (
            "v68 must fix existing sources, not pad the registry"
        )


# ============================================================
# telegram_sender.py — employer-context evidence
# ============================================================

class TestV68EmployerContext:
    """Bank/company listings are not rejected only because a truncated
    listing lacks explicit cyber keywords."""

    def _enriched(self, job):
        from telegram_sender import _enrich_cyber_evidence, _publishable_cyber_evidence
        _enrich_cyber_evidence(job)
        return _publishable_cyber_evidence(job)

    def test_f5_solutions_engineer_passes_evidence_gate(self):
        """'Solutions Engineer @ F5' with real security skills in the
        description must reach enriched_employer_context evidence."""
        job = Job(
            title="Solutions Engineer",
            company="F5",
            location="Remote",
            url="https://www.f5.com/careers/job/123",
            description="Design secure application delivery architectures; "
                        "experience with WAF, VPN, and zero trust deployments.",
            source="f5",
            cyber_verdict=CyberVerdict.LIKELY.value,
            cyber_probability=0.7,
            source_key="f5_careers",
            provenance_hash="f5p1",
        )
        code, _ = self._enriched(job)
        assert code in ("enriched_vendor_security_context", "enriched_employer_context"), (
            f"F5 listing with security skills must pass the LIKELY gate, got {code}"
        )

    def test_f5_word_bounded_no_false_positive(self):
        """A company whose name merely CONTAINS 'f5' (e.g. 'Affable Labs')
        must NOT inherit F5's vendor identity — the gate holds for a bare
        job noun from an unknown employer."""
        job = Job(
            title="Support Specialist",
            company="Affable Labs",
            location="Cairo, Egypt",
            url="https://affable.example.com/jobs/4",
            description="Customer support and general IT assistance.",
            source="other",
            cyber_verdict=CyberVerdict.LIKELY.value,
            cyber_probability=0.5,
            source_key="other",
            provenance_hash="alp1",
        )
        code, _ = self._enriched(job)
        assert code == "insufficient_cyber_evidence", (
            "substrate match must not bypass the LIKELY evidence gate"
        )

    def test_valeo_ai_architect_passes_with_description_skills(self):
        """'AI Architect @ Valeo' (automotive, infrastructure-adjacent)
        passes when the description carries real security skills AND Valeo
        has proven cyber yield for this bot (historical acceptance)."""
        job = Job(
            title="AI Architect",
            company="Valeo",
            location="Cairo, Egypt",
            url="https://valeo.example.com/jobs/9",
            description="Build secure cloud architecture and zero trust "
                        "infrastructure for manufacturing platforms.",
            source="valeo",
            cyber_verdict=CyberVerdict.LIKELY.value,
            cyber_probability=0.65,
            source_key="valeo_egypt",
            provenance_hash="vp1",
        )
        with mock.patch(
            "telegram_sender._proven_employer_context", return_value=True,
        ):
            code, _ = self._enriched(job)
        assert code == "enriched_employer_context", (
            f"Valeo AI Architect with proven employer context must pass, got {code}"
        )

    def test_unknown_employer_noun_still_fails(self):
        """A generic 'Solutions Engineer' from an unknown company without
        proven yield stays below the gate — the v62 contract."""
        job = Job(
            title="Solutions Engineer",
            company="Acme Trading",
            location="Cairo, Egypt",
            url="https://acme.example.com/jobs/2",
            description="Deliver product implementations to enterprise clients.",
            source="other",
            cyber_verdict=CyberVerdict.LIKELY.value,
            cyber_probability=0.4,
            source_key="other",
            provenance_hash="ap1",
        )
        with mock.patch(
            "telegram_sender._proven_employer_context", return_value=False,
        ):
            code, _ = self._enriched(job)
        assert code == "insufficient_cyber_evidence"

    def test_title_noun_alone_does_not_bypass(self):
        """An infrastructure-adjacent title with an empty description and
        an unproven employer still fails — the title alone is never enough."""
        job = Job(
            title="Cloud Infrastructure Engineer",
            company="Globex",
            location="Riyadh, Saudi Arabia",
            url="https://globex.example.com/jobs/3",
            description="",
            source="other",
            cyber_verdict=CyberVerdict.LIKELY.value,
            cyber_probability=0.5,
            source_key="other",
            provenance_hash="gp1",
        )
        with mock.patch(
            "telegram_sender._proven_employer_context", return_value=False,
        ):
            code, _ = self._enriched(job)
        assert code == "insufficient_cyber_evidence"

    def test_proven_employer_still_requires_skills_and_title(self):
        """Even a proven employer does not make a pure job noun publishable —
        both an adjacent title and real description skills are required."""
        job = Job(
            title="Sales Operations Coordinator",
            company="F5",
            location="Remote",
            url="https://www.f5.com/careers/job/456",
            description="Support quota planning and pipeline reporting.",
            source="f5",
            cyber_verdict=CyberVerdict.LIKELY.value,
            cyber_probability=0.5,
            source_key="f5_careers",
            provenance_hash="fp2",
        )
        # F5's own domain sits in the job URL, which already names the
        # employer's vendor identity — but a business/support noun is still
        # a non-cyber role even at a security vendor: the gate holds for
        # non-technical titles exactly as the v62 contract requires.
        code, _ = self._enriched(job)
        assert code == "insufficient_cyber_evidence", (
            "vendor identity alone must not carry non-security roles"
        )


# ============================================================
# linkedin_hr_posts_scraper.py — final fix
# ============================================================

class TestV68HrPostsFinal:
    """Dedicated discovery lanes, direct post verification, and CSE streak
    parking."""

    def test_dedicated_lanes_produce_methods(self):
        from sources import linkedin_hr_posts_scraper as hps

        slot = int(time.time() // (4 * 3600))
        methods = [m["method"] for m in (
            hps._build_recruiter_posts_lane(slot)
            + hps._build_company_hiring_posts_lane(slot)
            + hps._build_job_announcements_lane(slot)
        )]
        assert methods.count("recruiter_posts") >= 1
        assert methods.count("company_hiring_posts") >= 1
        assert methods.count("job_announcements") >= 1

    def test_lane_queries_carry_post_voice_templates(self):
        from sources import linkedin_hr_posts_scraper as hps

        # Rotation makes only a subset of the lane visible in the current
        # slot — assert the voice templates exist anywhere in the template
        # pools instead, so the test is not rotation-dependent.
        pool = " ".join(
            q["query"]
            for s in range(4)
            for q in (hps._build_recruiter_posts_lane(s)
                      + hps._build_company_hiring_posts_lane(s)
                      + hps._build_job_announcements_lane(s))
        )
        for voice in ['\"I\'m hiring\"', '\"#hiring\"', '\"send me your CV\"', '\"DM me\"']:
            assert voice in pool, f"lane voice template {voice} missing"

    def test_post_verification_accepts_real_hiring_post(self):
        """A body carrying both hiring intent and a security-role signal
        passes the direct URL verification."""
        from sources import linkedin_hr_posts_scraper as hps

        hiring_html = (
            "<html><body><div class='feed-update'>We are hiring a Security Engineer "
            "for our Cairo cybersecurity team! Send CV to hr@example.com. "
            "Responsibilities include SIEM monitoring, incident response, and "
            "zero trust architecture reviews across the EMEA region.</div></body></html>"
        )
        with mock.patch("sources.linkedin_hr_posts_scraper.get_text", return_value=hiring_html), \
             mock.patch("sources.linkedin_hr_posts_scraper._extract_text_from_html",
                        return_value=hiring_html):
            accepted, evidence = hps._verify_post_url("https://linkedin.com/posts/test")

        assert accepted
        assert evidence == "verified_hiring_and_role"

    def test_post_verification_declines_article_without_role(self):
        """A page with hiring words but no security role is declined as
        no_role_evidence instead of entering the scrape gate."""
        from sources import linkedin_hr_posts_scraper as hps

        article_html = (
            "<html><body><p>We are hiring accountants in Cairo today! The finance "
            "team is expanding rapidly and looking for qualified candidates who "
            "hold a bachelor's degree in accounting with five years of experience "
            "in financial reporting and audits across the MENA region.</p></body></html>"
        )
        with mock.patch("sources.linkedin_hr_posts_scraper.get_text", return_value=article_html), \
             mock.patch("sources.linkedin_hr_posts_scraper._extract_text_from_html",
                        return_value=article_html):
            accepted, evidence = hps._verify_post_url("https://linkedin.com/posts/test")

        assert not accepted
        assert evidence == "no_role_evidence"

    def test_post_verification_declines_news_page(self):
        from sources import linkedin_hr_posts_scraper as hps

        news_html = (
            "<html><body><p>Cybersecurity threats are rising in Egypt and across the "
            "region. Analysts say so many enterprises are investing heavily in "
            "defence stacks, while regional CERTs warn of an uptick in phishing "
            "campaigns targeting banking customers during the last quarter.</p></body></html>"
        )
        with mock.patch("sources.linkedin_hr_posts_scraper.get_text", return_value=news_html), \
             mock.patch("sources.linkedin_hr_posts_scraper._extract_text_from_html",
                        return_value=news_html):
            accepted, evidence = hps._verify_post_url("https://linkedin.com/posts/test")

        assert not accepted
        assert evidence == "no_hiring_intent"

    def test_cse_failure_streak_parks_backend(self):
        """CSE persistent failures now park the backend like any other —
        the v68 diagnosis showed CSE backoff firing twice then being
        re-hit every query."""
        from sources import linkedin_hr_posts_scraper as hps

        # Force the failure counter past the park cap.
        hps._cse_backoff_count = 0
        hps._backend_parked.discard("google_cse")
        for _ in range(hps._BACKEND_PARK_STREAK + 2):
            hps._set_cse_backoff(5.0)
            hps._search_via_google_cse("site:linkedin.com/posts #hiring cybersecurity Egypt")
        assert "google_cse" in hps._backend_parked, (
            "CSE must be parked after persistent failures like other backends"
        )
        # Housekeeping: leave module state clean for other tests.
        hps._backend_parked.discard("google_cse")
        hps._cse_backoff_count = 0
        hps._cse_backoff_until = 0.0

    def test_post_verification_records_rejection_telemetry(self):
        """A declined pre-scrape URL records its rejection reason in the
        run telemetry instead of silently passing into the scoring gate."""
        from sources import linkedin_hr_posts_scraper as hps

        hps._reset_hr_telemetry(budget_seconds=90, queries_planned=3)
        hps._record_rejection("no_hiring_intent")
        telemetry = hps.get_hr_post_telemetry()
        assert telemetry.get("rejections", {}).get("no_hiring_intent", 0) == 1
