import asyncio


def test_topic_thread_id_reads_env(monkeypatch):
    import config

    monkeypatch.setenv("TOPIC_EGYPT", "12345")
    assert config.get_topic_thread_id("egypt") == 12345

    monkeypatch.setenv("TOPIC_EGYPT", "not-an-int")
    assert config.get_topic_thread_id("egypt") is None


def test_jina_nav_artifact_filter():
    from sources.jina_scraper import _is_nav_artifact

    assert _is_nav_artifact('[Marketing Jobs](https://www.naukrigulf.com/marketing-jobs "Marketing Jobs")')
    assert _is_nav_artifact("Civil Engineering Jobs")
    assert not _is_nav_artifact("Endpoint Security Engineer")


def test_hn_comment_noise_filter():
    from sources.new_sources import _is_hn_comment

    assert _is_hn_comment("Hi jhartmann, your email is not in your profile")
    assert _is_hn_comment("Do you hire Canadians?")
    assert not _is_hn_comment("Acme Security | SOC Analyst | Remote | Full-Time")


def test_linkedin_timeout_returns_partial_results(monkeypatch):
    import sources.linkedin_unified as linkedin_unified

    async def slow_impl():
        linkedin_unified._LINKEDIN_PARTIAL_RESULTS = ["partial-job"]
        await asyncio.sleep(2)
        return ["late-job"]

    monkeypatch.setattr(linkedin_unified.config, "LINKEDIN_TOTAL_BUDGET_SECONDS", 1)
    monkeypatch.setattr(linkedin_unified, "_fetch_linkedin_unified_impl", slow_impl)

    assert asyncio.run(linkedin_unified.fetch_linkedin_unified_async()) == ["partial-job"]
