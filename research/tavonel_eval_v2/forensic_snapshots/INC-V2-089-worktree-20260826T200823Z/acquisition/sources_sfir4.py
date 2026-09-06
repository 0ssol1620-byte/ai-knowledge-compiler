"""Prospective metadata-only universe for independent replication SFIR4.

SFIR4 is a separate protocol.  Git roots are fresh and Git discovery uses
bounded, non-recursive tree-object traversal; this module has no payload reader.
"""

from __future__ import annotations

from types import MappingProxyType

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4"
FAMILY_AUTHORITIES = MappingProxyType(
    {
        "git_docs": "GITHUB_IMMUTABLE_NONRECURSIVE_GIT_TREE_BFS_API_V1",
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
SELECTION_SALT = "sfir4-capacity-v1:2026-08-27:nonrecursive-tree-bfs"

# Memory and Git API request bounds are independent.  A bound hit excludes the
# root as incomplete; it never asserts that the root has zero candidates.
MAX_METADATA_RESPONSE_BYTES = 16 * 1024 * 1024
METADATA_READ_BLOCK_BYTES = 64 * 1024
MAX_GIT_TREE_OBJECTS_PER_ROOT = 158
MAX_GIT_TREE_QUEUE_ENTRIES = 256
MAX_GIT_TREE_AGGREGATE_BYTES_PER_ROOT = 512 * 1024 * 1024
MAX_GIT_API_REQUESTS_PER_ROOT = 240
MAX_GIT_API_REQUESTS_GLOBAL = 4800
MAX_GIT_RETAINED_DOC_PATHS_PER_ROOT = 80
MAX_GIT_TRAVERSAL_IDENTITIES_PER_ROOT = 512
MAX_RATE_LIMIT_WAIT_SECONDS = 60
MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS = 180
RETRYABLE_HTTP_BACKOFF_SECONDS = 5
MAX_ECFR_VERSION_AGGREGATE_STATE_BYTES = 64 * 1024 * 1024
ECFR_VERSION_KEY_OVERHEAD_BYTES = 64
ECFR_VERSION_DATE_OVERHEAD_BYTES = 16

SFIR3_GIT_ROOTS = (
    "tensorflow/tensorflow",
    "keras-team/keras",
    "apache/arrow",
    "kubernetes/kubernetes",
    "ansible/ansible",
    "redis/redis",
    "mongodb/mongo",
    "denoland/deno",
    "llvm/llvm-project",
    "eclipse-openj9/openj9",
    "fastapi/fastapi",
    "tiangolo/typer",
    "agronholm/anyio",
    "python/importlib_metadata",
    "pyca/cryptography",
    "paramiko/paramiko",
    "fabric/fabric",
    "boto/boto3",
    "aws/aws-cli",
    "googleapis/python-api-core",
    "googleapis/google-cloud-python",
    "microsoft/TypeScript",
    "facebook/react",
    "vuejs/core",
    "nestjs/nest",
    "expressjs/express",
    "webpack/webpack",
    "babel/babel",
    "pnpm/pnpm",
    "yarnpkg/berry",
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
SFIR2_GIT_ROOTS = (
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
)

SOURCE_POOLS = MappingProxyType(
    {
        "git_docs": {
            "repositories": (
                "urllib3/urllib3",
                "pallets/itsdangerous",
                "pytest-dev/pluggy",
                "pytest-dev/pytest-asyncio",
                "python-attrs/attrs",
                "python-jsonschema/jsonschema",
                "python-hyper/h2",
                "duckdb/duckdb",
                "apache/avro",
                "apache/thrift",
                "github/rest-api-description",
                "docker/cli",
                "grpc/grpc",
                "protocolbuffers/protobuf",
                "curl/curl",
                "git/git",
                "tornadoweb/tornado",
                "benoitc/gunicorn",
                "MagicStack/uvloop",
                "jazzband/pip-tools",
            ),
            "extensions": (".md", ".mdx", ".rst"),
            "max_candidates_per_repository": 80,
            "max_total_candidates": 1600,
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
        "unavailable_http_statuses": (404, 409, 451),
        "terminal_http_statuses": (401, 403),
        "require_complete_pagination": True,
        "refuse_on_cap_before_exhaustion": True,
    }
)


def normalize_wikipedia_category(category: str) -> str:
    return "_".join(category.removeprefix("Category:").strip().casefold().split())


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
    current = {value.casefold() for value in SOURCE_POOLS["git_docs"]["repositories"]}
    prior = {value.casefold() for value in (*SFIR1_GIT_ROOTS, *SFIR2_GIT_ROOTS, *SFIR3_GIT_ROOTS)}
    if len(current) != 20 or current & prior:
        raise RuntimeError("SFIR4 Git roots overlap SFIR1/SFIR2/SFIR3 or are not exactly 20")
    per_root_plan = (
        2
        + MAX_GIT_TREE_OBJECTS_PER_ROOT
        + SOURCE_POOLS["git_docs"]["max_candidates_per_repository"]
    )
    if per_root_plan != MAX_GIT_API_REQUESTS_PER_ROOT:
        raise RuntimeError(
            "SFIR4 per-root Git request bound differs from its frozen theoretical plan"
        )
    if len(current) * per_root_plan > MAX_GIT_API_REQUESTS_GLOBAL:
        raise RuntimeError("SFIR4 theoretical Git request plan exceeds the frozen global budget")


def assert_disjoint_from_comprehensive_spent(container_ids: object, alias_ids: object) -> None:
    if not isinstance(container_ids, (list, tuple, set)) or not isinstance(
        alias_ids, (list, tuple, set)
    ):
        raise RuntimeError("comprehensive spent identity sets are malformed")
    spent = {str(v).casefold() for v in (*container_ids, *alias_ids)}
    current = {discovery_root_id(f, r) for f in FAMILIES for r in declared_roots(f)}
    overlap = sorted(v for v in current if v.casefold() in spent)
    if overlap:
        raise RuntimeError(
            "SFIR4 roots overlap comprehensive historical spent set: " + ", ".join(overlap)
        )


assert_static_disjointness()
