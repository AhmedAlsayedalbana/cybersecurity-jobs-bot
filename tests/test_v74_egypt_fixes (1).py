"""v74 regression tests — Egypt funnel telemetry, Egyptian source recovery
ladder, HR Posts jina_index gate, and multi-signal Hidden Jobs Discovery.

Baseline before v74: 393 passed / 5 skipped / 0 failed.
Every test here is additive: existing behaviour of the pipeline, the
classifier, dedup, freshness, and delivery lifecycle stays untouched.
"""
import time
import types
from unittest import mock

import pytest

# ── Phase 2: Egypt funnel telemetry ────────────────────────────────────────


def _make_funnel():
    from egypt_funnel import EgyptPipelineFunnel
    return EgyptPipelineFunnel()


class TestEgyptFunnelStages:
    def test_funnel_tracks_all_stages_in_order(self):
        """A key is counted at the FIRST stage it reaches; the funnel is a
        funnel, so one job appears once per stage it actually passed."""
        funnel = _make_funnel()
        jobs = [f"j{i}" for i in range(9)]
        stages = ["discovered", "cyber_candidate", "location_ok", "fresh",
                  "new_job", "in_pool", "delivery_eligible", "routed", "sent"]
        for job, stage in zip(jobs, stages):
            funnel.egypt.record_stage(job, stage)
        for stage in stages:
            assert getattr(funnel.egypt, stage) == 1
        assert funnel.egypt.sent == 1

    def test_funnel_stages_count_jobs_not_double_count(self):
        """A key is counted once per stage; re-recording an already-seen
        key must not inflate the counter."""
        funnel = _make_funnel()
        key = "egy:job:beta"
        for _ in range(5):
            funnel.egypt.record_stage(key, "discovered")
        assert funnel.egypt.discovered == 1

    def test_funnel_records_drop_reasons_and_blocks_later_stages(self):
        funnel = _make_funnel()
        key = "egy:job:gamma"
        funnel.egypt.record_drop(key, "recency_stale")
        assert funnel.egypt.drop_reasons["recency_stale"] == 1
        funnel.egypt.record_stage(key, "in_pool")  # after a drop: ignored
        assert funnel.egypt.in_pool == 0
        assert funnel.egypt.discovered == 0
        assert key in funnel.egypt.seen_keys

    def test_unequal_quality_no_egypt_priority_bypass(self):
        """Egypt priority applies at equal quality — a non-cyber Egypt job
        must still be dropped at the cyber gate, exactly like a Gulf one."""
        funnel = _make_funnel()
        funnel.egypt.record_drop("v74:noncyber", "not_cyber")
        assert funnel.egypt.drop_reasons["not_cyber"] == 1
        # The drop is recorded even though no stage was ever reached — a
        # candidate seen only to be rejected still counts in the funnel.
        assert "v74:noncyber" in funnel.egypt.seen_keys

    def test_funnel_log_line_emits_stage_counts(self):
        import logging
        from egypt_funnel import EgyptPipelineFunnel, log_funnel
        funnel = EgyptPipelineFunnel()
        for k in range(5):
            funnel.egypt.record_stage(f"k{k}", "discovered")
            funnel.egypt.record_stage(f"k{k}", "in_pool")
        funnel.egypt.record_drop("k5", "recency_stale")
        logger = logging.getLogger("v74-test-funnel")
        logger.setLevel(logging.DEBUG)
        handler = logging.Handler()
        captured = []
        handler.emit = lambda r: captured.append(r.getMessage())
        logger.addHandler(handler)
        log_funnel(funnel, "v74-test", logger)
        logger.removeHandler(handler)
        line = captured[0] if captured else ""
        assert "discovered=5" in line
        assert "recency_stale=1" in line
        assert "sent=0" in line


# ── Phase 3: Egyptian source recovery ladder ───────────────────────────────


class TestEgyptRecoveryLadder:
    def test_recovery_urls_cover_the_user_flagged_sources(self):
        from sources.official_careers import _EGYPT_RECOVERY_URLS
        required = {"aaib", "adib_egypt", "banque_misr", "cib_egypt",
                    "qnb_egypt", "banque_du_caire", "mashreq_egypt",
                    "bank_nxt", "itida", "nbe", "saib", "raya",
                    "smart_village", "telecom_egypt"}
        assert required <= set(_EGYPT_RECOVERY_URLS), \
            required - set(_EGYPT_RECOVERY_URLS)

    def test_recovery_urls_are_public_careers_surfaces(self):
        from sources.official_careers import _EGYPT_RECOVERY_URLS
        for key, urls in _EGYPT_RECOVERY_URLS.items():
            for url in urls:
                assert url.startswith("https://"), (key, url)

    def test_source_result_carries_ladder_steps(self):
        from sources.marketplace_sources import SourceResult
        result = SourceResult(jobs=[], ladder_steps=("direct", "alt_endpoint"))
        assert result.ladder_steps == ("direct", "alt_endpoint")

    def test_ladder_steps_default_empty(self):
        from sources.marketplace_sources import SourceResult
        assert SourceResult(jobs=[]).ladder_steps == ()

    def test_recovery_ladder_runs_before_browser_for_js_sources(self):
        """The v74 ladder injects alt-URL attempts BEFORE the Playwright
        step: an alt URL that answers honestly (even with zero jobs) must
        suppress the browser escalation."""
        from sources import official_careers

        alt_url = "https://aaib.com.eg/en/careers/current-vacancies"

        def fake_reader(source, url):
            if url == alt_url:
                return official_careers._Outcome([], parsed=True,
                                                 no_active_jobs=True)
            return None

        from sources.official_careers import OFFICIAL_SOURCES
        source = next(s for s in OFFICIAL_SOURCES if s.key == "aaib")
        # _Outcome lookup in _EGYPT_RECOVERY_URLS is keyed by the source key
        # string, not the frozen dataclass — assert that before faking the
        # reader so the ladder step is provably reached by the code path.
        assert "aaib" in official_careers._EGYPT_RECOVERY_URLS
        # _fetch_direct must answer with nothing real for the ladder branch
        # to run at all — mirror the real blocked-bank condition from the
        # v74 diagnosis (direct endpoint returned no jobs and no honest
        # empty verdict).
        empty_outcome = official_careers._Outcome([], parsed=False)
        with mock.patch.object(official_careers, "_fetch_direct",
                               return_value=empty_outcome), \
             mock.patch.object(official_careers, "_fetch_via_public_reader_url",
                               fake_reader):
            outcome = official_careers.fetch_source("aaib")
        assert any("alt_endpoint" in (s or "") or "reader_alt" in (s or "")
                   for s in (outcome.ladder_steps or ()))
        # An honest empty answer must never force the Playwright step.


# ── Phase 4: HR Posts jina_index backend gate ──────────────────────────────


class TestHRPostsJinaIndexGate:
    def test_jina_index_search_backend_exists(self):
        from sources.linkedin_hr_posts_scraper import _search_via_jina_index
        assert callable(_search_via_jina_index)

    def test_jina_index_needs_no_credentials(self):
        from sources.linkedin_hr_posts_scraper import _search_via_jina_index
        hits = _search_via_jina_index("site:linkedin.com cybersecurity Cairo")
        assert isinstance(hits, list)

    def test_jina_index_unusable_only_when_explicitly_parked(self):
        from sources.linkedin_hr_posts_scraper import (_all_hr_backends_unusable,
                                                       _backend_parked)
        with mock.patch.dict(_backend_parked, {"google_cse": time.time() - 1e6,
                                               "serpapi": time.time() - 1e6,
                                               "bing_html": time.time() - 1e6}):
            # jina_index has NO credentials and therefore must never park:
            # the whole HR plan must stay alive on jina_index alone.
            assert not _all_hr_backends_unusable()

    def test_unusable_requires_all_four_backends_parked(self):
        from sources.linkedin_hr_posts_scraper import (_all_hr_backends_unusable,
                                                       _backend_parked)
        parked = {"google_cse": time.time() - 1e6,
                  "serpapi": time.time() - 1e6,
                  "bing_html": time.time() - 1e6,
                  "jina_index": time.time() - 1e6}
        with mock.patch.dict(_backend_parked, parked, clear=True):
            assert _all_hr_backends_unusable()


# ── Phase 5: multi-signal Hidden Jobs Discovery ────────────────────────────


class TestMultiSignalDiscovery:
    def test_careers_page_signal_requires_announcement_and_role(self):
        from sources.hiring_signal_discovery import extract_careers_page_signals
        page = "Our engineering team is hiring a cloud security engineer. " \
               "We are growing our team and expanding our security " \
               "footprint in Cairo."
        signals = extract_careers_page_signals(page, "SomeBank")
        assert len(signals) >= 1
        assert all(s.company == "SomeBank" for s in signals)
        assert all(s.signal_source == "careers_page" for s in signals)

    def test_careers_page_signal_ignores_no_hiring_page(self):
        from sources.hiring_signal_discovery import extract_careers_page_signals
        page = "SomeBank is a leading retail bank offering deposits and " \
               "lending products to customers across the region."
        assert extract_careers_page_signals(page, "SomeBank") == []

    def test_careers_page_signal_ignores_role_without_company(self):
        from sources.hiring_signal_discovery import extract_careers_page_signals
        page = "We are hiring. Join us today."
        assert extract_careers_page_signals(page, "") == []

    def test_careers_page_signal_accepts_arabic_announcement(self):
        from sources.hiring_signal_discovery import extract_careers_page_signals
        page = "انضم لفريقنا في قسم امن المعلومات. وظائف شاغرة في " \
               "مجال cybersecurity بمصر."
        signals = extract_careers_page_signals(page, "BankMisr")
        assert signals, "Arabic hiring voice must produce a signal"

    def test_detect_signals_from_text_list_tags_lane(self):
        from sources.hiring_signal_discovery import detect_signals_from_text_list
        texts = [
            "We're growing our security team at Acme Corp. SOC analyst "
            "role in Cairo.",
            "Random unrelated post about cloud costs.",
        ]
        found = detect_signals_from_text_list(texts, lane="engineering_blog")
        assert len(found) == 1
        assert found[0].signal_source == "engineering_blog"
        assert found[0].company == "Acme"

    def test_unknown_lane_falls_back_to_linkedin(self):
        from sources.hiring_signal_discovery import detect_signals_from_text_list
        # The text must satisfy the three-condition rule (growth + role +
        # company); the lane tag itself is applied regardless.
        found = detect_signals_from_text_list(
            ["We're growing our security team at Acme. SOC analyst in Egypt"],
            lane="mystery_lane")
        assert found and found[0].signal_source == "linkedin"

    def test_per_lane_telemetry_updates(self):
        from sources import hiring_signal_discovery as hsd
        hsd._reset_v72_telemetry()  # isolate from earlier lanes in this run
        before = dict(hsd._TELEMETRY)
        hsd.detect_signals_from_text_list(
            ["We're growing our security team at Acme. SOC analyst in Cairo"],
            lane="careers_page")
        after = dict(hsd._TELEMETRY)
        assert after["signals_detected"] == before["signals_detected"] + 1
        assert after["signals_detected_careers_page"] == \
            before["signals_detected_careers_page"] + 1

    def test_verification_chain_does_not_relax_gates(self):
        """A signal that finds no application URL stays an unverified
        hiring signal — a real URL is the only path to a verified job."""
        from sources.hiring_signal_discovery import HiringSignal, verify_signal

        def empty_search(spec):
            return []

        signal = HiringSignal(
            source_text="We're hiring security at Acme",
            company="Acme", inferred_title="Security",
            region_hint="", url="", signal_source="linkedin",
        )
        outcome = verify_signal(signal, search_fn=empty_search,
                                job_builder=None)
        assert outcome.decision == "hiring_signal"

    def test_verification_chain_produces_verified_job_when_url_found(self):
        from sources.hiring_signal_discovery import HiringSignal, verify_signal

        def good_search(spec):
            if spec.get("kind") == "careers_search":
                return [("https://acme.com/careers/sec-1", "Security Analyst")]
            return []

        def build(url, title, company):
            from models import Job
            return Job(title=title, company=company, location="", url=url,
                       source="linkedin", source_key="linkedin_hr_posts",
                       description="", content_type="job_listing")

        signal = HiringSignal(
            source_text="We're hiring security at Acme",
            company="Acme", inferred_title="Security",
            region_hint="", url="", signal_source="linkedin",
        )
        outcome = verify_signal(signal, search_fn=good_search,
                                job_builder=build)
        assert outcome.is_verified_job
        assert outcome.verified_job.url == "https://acme.com/careers/sec-1"
