"""Prospective metadata-only source design for independent replication SFIR2.

This module contains the complete finite root universe.  It intentionally has
no payload reader.  A capacity probe may inspect identity, aliases and revision
availability only.
"""

from __future__ import annotations

from types import MappingProxyType

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V2"

FAMILY_AUTHORITIES = MappingProxyType(
    {
        "git_docs": "GITHUB_REPOSITORY_METADATA_API_V1",
        "regulation_ecfr": "ECFR_VERSIONER_METADATA_API_V1",
        "encyclopedia_wikipedia": "MEDIAWIKI_PAGE_REVISION_METADATA_API_V1",
    }
)
FAMILIES = tuple(FAMILY_AUTHORITIES)

CANDIDATE_FIELDS = (
    "discovery_root_id",
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
SELECTION_SALT = "sfir2-capacity-v1:2026-08-26:fresh-independent-replication"
MAX_METADATA_RESPONSE_BYTES = 16 * 1024 * 1024
METADATA_READ_BLOCK_BYTES = 64 * 1024

# These Git and Wikipedia roots have no exact normalized overlap with SFIR1.
SOURCE_POOLS = MappingProxyType(
    {
        "git_docs": {
            "repositories": (
                "ipython/ipython",
                "pytest-dev/pytest",
                "tox-dev/tox",
                "psf/black",
                "python/mypy",
                "python/typeshed",
                "pallets/click",
                "pallets/jinja",
                "pallets/werkzeug",
                "sqlalchemy/alembic",
                "aio-libs/yarl",
                "aio-libs/multidict",
                "pydantic/pydantic-core",
                "astral-sh/ty",
                "encode/httpx",
                "encode/databases",
                "encode/httpcore",
                "rust-lang/cargo",
                "rust-lang/rust-clippy",
                "rust-lang/rustfmt",
                "tokio-rs/tokio",
                "serde-rs/serde",
                "BurntSushi/ripgrep",
                "sharkdp/bat",
                "junegunn/fzf",
                "neovim/neovim",
                "vim/vim",
                "PowerShell/PowerShell",
                "dotnet/runtime",
                "dotnet/sdk",
            ),
            "extensions": (".md", ".mdx", ".rst"),
            "max_candidates_per_repository": 80,
            "max_total_candidates": 2400,
        },
        "regulation_ecfr": {
            "titles": tuple(range(1, 51)),
            "max_version_pages_per_title": 250,
            "max_version_records_per_title": 100_000,
            "max_candidates_per_title": 30,
            "max_total_candidates": 1500,
        },
        "encyclopedia_wikipedia": {
            "api_project": "en.wikipedia.org",
            "namespace": 0,
            "category_roots": (
                "Astronomy",
                "Physics",
                "Chemistry",
                "Biology",
                "Mathematics",
                "Statistics",
                "Geology",
                "Meteorology",
                "Oceanography",
                "Ecology",
                "Genetics",
                "Neuroscience",
                "Immunology",
                "Virology",
                "Pharmacology",
                "Surgery",
                "Architecture",
                "Economics",
                "Sociology",
                "Psychology",
                "Anthropology",
                "Linguistics",
                "Philosophy",
                "Political science",
                "Law",
                "Education",
                "Engineering",
                "Electronics",
                "Telecommunications",
                "Transportation",
            ),
            "max_category_pages_per_root": 100,
            "category_page_size": 500,
            "max_candidates_per_category": 150,
            "revision_batch_size": 50,
            "max_total_candidates": 4500,
        },
    }
)

PAGINATION_CONTRACT = MappingProxyType(
    {
        "maximum_retries_per_request": 5,
        "retryable_http_statuses": (429, 500, 502, 503, 504),
        "zero_candidate_http_statuses": (404, 409, 451),
        "terminal_http_statuses": (401, 403),
        "require_complete_pagination": True,
        "refuse_on_cap_before_exhaustion": True,
    }
)

SFIR1_GIT_ROOTS = (
    "elastic/docs-content",
    "vitejs/vitepress",
    "python/peps",
    "django/djangoproject.com",
    "pallets/flask",
    "uvicorn/uvicorn",
    "encode/starlette",
    "aio-libs/aiohttp",
    "python-trio/trio",
    "scrapy/scrapy",
    "django/channels",
    "python-poetry/poetry",
    "Textualize/rich",
    "Textualize/textual",
    "prompt-toolkit/python-prompt-toolkit",
    "jupyterlab/jupyterlab",
    "squidfunk/mkdocs-material",
    "getsentry/sentry",
    "Homebrew/brew",
    "ziglang/zig",
)
SFIR1_WIKIPEDIA_ROOTS = (
    "Software documentation",
    "Free software",
    "Open-source software",
    "Programming languages",
    "Computer programming",
    "Databases",
    "Database management systems",
    "Operating systems",
    "Cloud computing",
    "Distributed computing",
    "Computer security",
    "Algorithms",
    "Internet protocols",
    "Web development",
    "Machine learning",
    "Artificial intelligence",
    "Data management",
    "Information retrieval",
    "Natural language processing",
    "Software engineering",
)


def normalize_wikipedia_category(category: str) -> str:
    value = category.removeprefix("Category:").strip().casefold()
    return "_".join(value.split())


def discovery_root_id(family: str, root: object) -> str:
    if family == "git_docs":
        return f"git:{str(root).casefold()}"
    if family == "regulation_ecfr":
        return f"ecfr:title:{int(root)}"
    if family == "encyclopedia_wikipedia":
        return "wikipedia:en:category:" + normalize_wikipedia_category(str(root))
    raise ValueError(f"unknown family {family}")


def declared_roots(family: str) -> tuple[object, ...]:
    pool = SOURCE_POOLS[family]
    if family == "git_docs":
        return tuple(pool["repositories"])
    if family == "regulation_ecfr":
        return tuple(pool["titles"])
    return tuple(pool["category_roots"])


def root_container_id(
    family: str, *, repository: str = "", title: str = "", part: str = "", category: str = ""
) -> str:
    if family == "git_docs" and repository:
        return discovery_root_id(family, repository)
    if family == "regulation_ecfr" and title and part:
        return f"ecfr:{int(title)}:{part}"
    if family == "encyclopedia_wikipedia" and category:
        return discovery_root_id(family, category)
    raise ValueError(f"incomplete root identity for {family}")


def assert_static_disjointness() -> None:
    current_git = {str(v).casefold() for v in SOURCE_POOLS["git_docs"]["repositories"]}
    prior_git = {v.casefold() for v in SFIR1_GIT_ROOTS}
    current_wiki = {
        normalize_wikipedia_category(v)
        for v in SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"]
    }
    prior_wiki = {normalize_wikipedia_category(v) for v in SFIR1_WIKIPEDIA_ROOTS}
    if current_git & prior_git or current_wiki & prior_wiki:
        raise RuntimeError("SFIR2 static roots overlap SFIR1")


def assert_disjoint_from_comprehensive_spent(container_ids: object, alias_ids: object) -> None:
    if not isinstance(container_ids, (list, tuple, set)) or not isinstance(
        alias_ids, (list, tuple, set)
    ):
        raise RuntimeError("comprehensive spent identity sets are malformed")
    spent = {str(value).casefold() for value in (*container_ids, *alias_ids)}
    current = {
        discovery_root_id(family, root) for family in FAMILIES for root in declared_roots(family)
    }
    overlap = sorted(value for value in current if value.casefold() in spent)
    if overlap:
        raise RuntimeError(
            "SFIR2 roots overlap comprehensive historical spent set: " + ", ".join(overlap)
        )


assert_static_disjointness()
