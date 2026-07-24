"""Source registry exports."""

from sources.source_registry import SourceSpec, get_source_specs


def build_legacy_fetchers() -> list[tuple[str, callable]]:
    """Compatibility layer for older tests/modules expecting tuple fetchers."""
    return [(spec.name, spec.fetcher) for spec in get_source_specs()]


ALL_FETCHERS = build_legacy_fetchers()

