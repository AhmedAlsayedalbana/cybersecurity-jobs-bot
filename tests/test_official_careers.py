from dataclasses import replace
from types import SimpleNamespace

from sources import official_careers as careers


def test_catalog_has_every_requested_source_exactly_once():
    expected = {
        "forasna", "shaghalni", "vodafone_egypt", "orange_egypt", "telecom_egypt",
        "banque_misr", "nbe", "cib_egypt", "qnb_egypt", "banque_du_caire",
        "valeo_egypt", "ibm_egypt", "microsoft_egypt", "siemens_egypt",
        "naukrigulf", "jobzella", "dubizzle", "laimoon", "stc_ksa", "aramco",
        "sabic", "neom", "qiddiya", "elm", "qatarenergy", "ooredoo",
        "etisalat_uae", "emirates_group", "flydubai", "hackerone", "bugcrowd",
        "cloudflare", "crowdstrike", "palo_alto_networks", "fortinet", "rapid7",
        "tenable", "wiz", "check_point", "cisco", "google_careers",
        "microsoft_security", "amazon_aws", "mandiant_google_cloud_security",
    }
    keys = [source.key for source in careers.OFFICIAL_SOURCES]
    assert set(keys) == expected
    assert len(keys) == len(set(keys)) == 44


def test_greenhouse_normalizes_real_job_fields(monkeypatch):
    monkeypatch.setattr(
        careers,
        "get_json",
        lambda *_args, **_kwargs: {
            "jobs": [{
                "id": 123,
                "title": "Security Engineer",
                "absolute_url": "https://boards.greenhouse.io/bugcrowd/jobs/123",
                "location": {"name": "Remote - Egypt"},
                "updated_at": "2026-07-20T10:00:00Z",
                "content": "Protect customer systems.",
            }],
        },
    )

    result = careers.fetch_source("bugcrowd")

    assert result.status == "success"
    assert result.transport == "direct"
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert (job.title, job.company, job.location) == ("Security Engineer", "Bugcrowd", "Remote - Egypt")
    assert job.source == job.source_key == "bugcrowd"
    assert job.extraction_method == "official:greenhouse"
    assert job.posted_date is not None


def test_workday_fetches_every_page_and_deduplicates(monkeypatch):
    calls = []

    def fake_post(_url, payload=None, **_kwargs):
        offset = payload["offset"]
        calls.append(offset)
        if offset == 0:
            return {
                "total": 3,
                "jobPostings": [
                    {"title": "Threat Researcher", "externalPath": "/job/one", "locationsText": "Cairo"},
                    {"title": "Security Engineer", "externalPath": "/job/two", "locationsText": "Remote"},
                ],
            }
        return {
            "total": 3,
            "jobPostings": [
                {"title": "Security Engineer", "externalPath": "/job/two", "locationsText": "Remote"},
            ],
        }

    monkeypatch.setattr(careers, "post_json", fake_post)
    source = replace(careers.SOURCES_BY_KEY["crowdstrike"], page_size=2)
    outcome = careers._fetch_workday(source)

    assert calls == [0, 2]
    assert len(outcome.jobs) == 2
    assert {job.url for job in outcome.jobs} == {
        "https://crowdstrike.wd5.myworkdayjobs.com/job/one",
        "https://crowdstrike.wd5.myworkdayjobs.com/job/two",
    }


def test_json_ld_html_is_accepted_but_navigation_is_not(monkeypatch):
    html = """
      <a href=\"/jobs\">View all jobs</a>
      <script type=\"application/ld+json\">{
        \"@context\": \"https://schema.org\", \"@type\": \"JobPosting\",
        \"title\": \"SOC Analyst\", \"url\": \"/job/soc-42\",
        \"datePosted\": \"2026-07-20\",
        \"hiringOrganization\": {\"name\": \"Forasna Employer\"},
        \"jobLocation\": {\"address\": {\"addressLocality\": \"Cairo\", \"addressCountry\": \"EG\"}}
      }</script>
    """
    monkeypatch.setattr(careers, "get_text_result", lambda *_a, **_k: SimpleNamespace(text=html, error_code=""))

    result = careers.fetch_source("forasna")

    assert result.status == "success"
    assert [(job.title, job.company, job.location) for job in result.jobs] == [("SOC Analyst", "Forasna Employer", "Cairo, EG")]


def test_confirmed_empty_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(careers, "get_json", lambda *_a, **_k: {"jobs": []})

    result = careers.fetch_source("cloudflare")

    assert result.jobs == []
    assert result.status == "empty"
    assert result.error_code == "no_active_jobs"


def test_unavailable_page_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(careers, "get_text_result", lambda *_a, **_k: SimpleNamespace(text=None, error_code="transport_or_rejected"))

    result = careers.fetch_source("rapid7")

    assert result.jobs == []
    assert result.status == "blocked"
    assert result.error_code == "transport_or_rejected"


def test_html_pagination_stops_at_max_pages_when_content_never_repeats(monkeypatch):
    # Regression test for the 2026-07-21 incident: mandiant_google_cloud_security
    # walked to page=3187 (~41 minutes) because every page it fetched produced a
    # slightly different fingerprint (JS-SPA noise, not real duplicate listings),
    # so the "stop on repeated fingerprint" condition never fired. The fetch must
    # be bounded by CareerSource.max_pages regardless of fingerprint uniqueness.
    calls = {"n": 0}

    def fake_get_text_result(*_args, **_kwargs):
        calls["n"] += 1
        i = calls["n"]
        html = f"""
          <script type="application/ld+json">{{
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Security Engineer {i}", "url": "/job/sec-{i}",
            "datePosted": "2026-07-20",
            "hiringOrganization": {{"name": "Rapid7"}},
            "jobLocation": {{"address": {{"addressLocality": "Remote", "addressCountry": "US"}}}}
          }}</script>
        """
        return SimpleNamespace(text=html, error_code="")

    monkeypatch.setattr(careers, "get_text_result", fake_get_text_result)

    source = next(s for s in careers.OFFICIAL_SOURCES if s.key == "rapid7")
    result = careers.fetch_source("rapid7")

    assert calls["n"] == source.max_pages
    assert len(result.jobs) == source.max_pages


def test_registry_registers_each_official_source_once():
    from sources.source_registry import get_source_specs

    counts = {}
    for spec in get_source_specs():
        counts[spec.key] = counts.get(spec.key, 0) + 1

    assert all(counts.get(key) == 1 for key in careers.OFFICIAL_SOURCE_KEYS)
    assert "cybersec_boards" not in counts
