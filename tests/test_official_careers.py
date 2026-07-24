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
        "semgrep", "vanta", "weaviate", "cato_networks", "mattermost", "sumo_logic",
        "cockroach_labs", "watchguard", "coalfire", "palantir", "lumin_digital",
        "true_zero_technologies", "visa",
    }
    keys = [source.key for source in careers.OFFICIAL_SOURCES]
    assert set(keys) == expected
    assert len(keys) == len(set(keys)) == 57


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


def test_lever_normalizes_public_posting(monkeypatch):
    monkeypatch.setattr(
        careers,
        "get_json",
        lambda *_args, **_kwargs: [{
            "id": "abc",
            "text": "Cloud Security Engineer",
            "hostedUrl": "https://jobs.lever.co/watchguard/abc",
            "createdAt": 1_784_000_000_000,
            "categories": {"location": "Remote", "commitment": "Full-time"},
            "descriptionPlain": "Build cloud security controls.",
        }],
    )

    result = careers.fetch_source("watchguard")

    assert result.status == "success"
    job = result.jobs[0]
    assert (job.title, job.location, job.source_key) == (
        "Cloud Security Engineer", "Remote", "watchguard",
    )
    assert job.posted_date is not None
    assert job.extraction_method == "official:lever"


def test_smartrecruiters_normalizes_public_posting(monkeypatch):
    monkeypatch.setattr(
        careers,
        "get_json",
        lambda *_args, **_kwargs: {
            "totalFound": 1,
            "content": [{
                "id": "12345",
                "name": "Information Security Analyst",
                "releasedDate": "2026-07-20T10:00:00Z",
                "company": {"name": "Visa"},
                "location": {"fullLocation": "Cairo, Egypt", "remote": False},
            }],
        },
    )

    result = careers.fetch_source("visa")

    assert result.status == "success"
    job = result.jobs[0]
    assert job.url == "https://jobs.smartrecruiters.com/Visa/12345-information-security-analyst"
    assert job.location == "Cairo, Egypt"
    assert job.posted_date is not None
    assert job.extraction_method == "official:smartrecruiters"


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


def test_registry_registers_each_official_source_once():
    from sources.source_registry import get_source_specs

    counts = {}
    for spec in get_source_specs():
        counts[spec.key] = counts.get(spec.key, 0) + 1

    assert all(counts.get(key) == 1 for key in careers.OFFICIAL_SOURCE_KEYS)
    assert "cybersec_boards" not in counts
