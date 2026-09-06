"""Metadata-only source contract for the independent SFI replication.

This module deliberately cannot fetch a document.  It only names the three
authorities from which a pre-acquisition capacity census may read identity and
revision-availability metadata.  Payload bytes, revision diffs, parsed units,
and SourceFacts belong after the protocol freeze.
"""

from __future__ import annotations

from types import MappingProxyType

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V1"

FAMILY_AUTHORITIES = MappingProxyType(
    {
        "git_docs": "GITHUB_REPOSITORY_METADATA_API_V1",
        "regulation_ecfr": "ECFR_VERSIONER_METADATA_API_V1",
        "encyclopedia_wikipedia": "MEDIAWIKI_PAGE_REVISION_METADATA_API_V1",
    }
)

FAMILIES = tuple(FAMILY_AUTHORITIES)

# A metadata candidate may carry a locator that a post-freeze worker can later
# dereference.  The object behind the locator is expressly not part of census.
CANDIDATE_FIELDS = (
        "root_container_id",
        "lineage_id",
        "family",
        "container_id",
        "alias_ids",
        "payload_ref",
        "revision_id",
        "revision_timestamp",
        "capability_exercise",
)

CAPABILITY_ENDPOINTS = ("E5", "E6", "E9")

# This is the complete, finite search design.  It is hashed into the design
# charter authority before any API is contacted.  A probe may return fewer
# candidates, but it may not widen these pools, page limits or caps afterward.
SELECTION_SALT = "sfir1-capacity-v1:2026-08-26:independent-replication"
SOURCE_POOLS = MappingProxyType(
    {
        "git_docs": {
            "repositories": (
                "elastic/docs-content", "vitejs/vitepress", "python/peps",
                "django/djangoproject.com", "pallets/flask", "uvicorn/uvicorn",
                "encode/starlette", "aio-libs/aiohttp", "python-trio/trio",
                "scrapy/scrapy", "django/channels", "python-poetry/poetry",
                "Textualize/rich", "Textualize/textual",
                "prompt-toolkit/python-prompt-toolkit", "jupyterlab/jupyterlab",
                "squidfunk/mkdocs-material", "getsentry/sentry", "Homebrew/brew",
                "ziglang/zig",
            ),
            "extensions": (".md", ".mdx", ".rst"),
            "max_tree_pages_per_repository": 100,
            "tree_page_size": 100,
            "max_candidates_per_repository": 80,
            "max_total_candidates": 3000,
        },
        "regulation_ecfr": {
            "titles": tuple(range(1, 51)),
            "max_version_pages_per_title": 250,
            "version_page_size": 100,
            "max_candidates_per_title": 30,
            "max_total_candidates": 3000,
        },
        "encyclopedia_wikipedia": {
            "api_project": "en.wikipedia.org",
            "namespace": 0,
            "category_roots": (
                "Software documentation", "Free software", "Open-source software",
                "Programming languages", "Computer programming", "Databases",
                "Database management systems", "Operating systems", "Cloud computing",
                "Distributed computing", "Computer security", "Algorithms",
                "Internet protocols", "Web development", "Machine learning",
                "Artificial intelligence", "Data management", "Information retrieval",
                "Natural language processing", "Software engineering",
            ),
            "max_category_pages_per_root": 100,
            "category_page_size": 500,
            "max_candidates_per_category": 150,
            "revision_batch_size": 50,
            "max_total_candidates": 3000,
        },
    }
)


def normalize_wikipedia_category(category: str) -> str:
    """Return the one frozen namespace used for category-root disjointness."""
    value = category.removeprefix("Category:").strip().casefold()
    return "_".join(value.split())


def root_container_id(
    family: str,
    *,
    repository: str = "",
    title: str = "",
    part: str = "",
    category: str = "",
) -> str:
    """Render an exact root id; document identities never substitute for it."""
    if family == "git_docs" and repository:
        return f"git:{repository.casefold()}"
    if family == "regulation_ecfr" and title and part:
        return f"ecfr:{int(title)}:{part}"
    if family == "encyclopedia_wikipedia" and category:
        return "wikipedia:en:category:" + normalize_wikipedia_category(category)
    raise ValueError(f"incomplete root identity for {family}")

PAGINATION_CONTRACT = MappingProxyType(
    {
        "maximum_retries_per_request": 5,
        "retryable_http_statuses": (429, 500, 502, 503, 504),
        "require_complete_pagination": True,
        "refuse_on_cap_before_exhaustion": True,
    }
)
