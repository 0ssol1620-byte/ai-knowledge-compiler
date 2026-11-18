"""Every ``runtime.serving`` block in the model registry names what the runner attests.

A recipe (a block without ``verdict``) launches ``image`` by digest under the served name
``<upstream_id>@<upstream_revision>``, which the chat runners require the server to echo.
A recipe on the AKC external protocol attests ``upstream_revision`` instead
(``attested_revision``). An image built from a Dockerfile in this repository has no digest
until it is built: such a block says ``built: false``, ``image: null`` and ``image_build``
(the Dockerfile); once ``built`` is true it names the image by digest with its build
provenance, and the image is the one of its own slot (``validate_registry``). A verdict block
records why there is no recipe; any image it names is still a digest. ``serving_variants`` (labelled
alternatives to the row's primary block) follow the same rules. Every row with a serving
block carries zero traffic.
"""

from __future__ import annotations

import copy
import hashlib
import re
import runpy
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _ROOT / "infra/model-registry/models.yaml"
_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")
_build_problems = runpy.run_path(str(_ROOT / "infra/model-registry/validate_registry.py"))[
    "serving_build_problems"
]


def _rows() -> list[dict[str, Any]]:
    releases = yaml.safe_load(_REGISTRY.read_text(encoding="utf-8"))["releases"]
    return [r for r in releases if isinstance((r.get("runtime") or {}).get("serving"), dict)]


def _blocks(row: dict[str, Any]) -> list[dict[str, Any]]:
    runtime = row["runtime"]
    return [runtime["serving"], *(runtime.get("serving_variants") or [])]


def _dockerfile_here(build: Any) -> bool:
    """A file named ``Dockerfile`` whose resolved path (links and ``..`` followed) is inside
    the repository."""
    if not isinstance(build, str) or not build:
        return False
    path = (_ROOT / build).resolve()
    return path.name == "Dockerfile" and path.is_relative_to(_ROOT) and path.is_file()


def _block_problems(row: dict[str, Any], serving: dict[str, Any]) -> list[str]:
    out = _build_problems(serving)
    unbuilt = serving.get("built") is False
    if "verdict" not in serving:
        if unbuilt:
            if serving.get("image") is not None:
                out.append("image named while built is false")
            if not _dockerfile_here(serving.get("image_build")):
                out.append("image_build is not a Dockerfile in this repository")
        elif not serving.get("image"):
            out.append("recipe without image")
        if serving.get("protocol") == "akc-external-runner":
            if serving.get("attested_revision") != row.get("upstream_revision"):
                out.append("attested_revision is not the upstream revision")
        elif not serving.get("served_model_name"):
            out.append("recipe without served_model_name")
    expected = f"{row.get('upstream_id')}@{row.get('upstream_revision')}"
    if "served_model_name" in serving and serving["served_model_name"] != expected:
        out.append(f"served_model_name is not {expected}")
    for field in ("image", "candidate_image"):
        if field not in serving or (field == "image" and unbuilt and serving[field] is None):
            continue
        if not _DIGEST.search(str(serving[field])):
            out.append(f"{field} carries no @sha256 digest")
    return out


def _problems(row: dict[str, Any]) -> list[str]:
    out = []
    if (row.get("rollout") or {}).get("traffic_percent") != 0:
        out.append("traffic_percent is not 0")
    for serving in _blocks(row):
        out += _block_problems(row, serving)
    return out


def test_every_serving_block_matches_its_row() -> None:
    rows = _rows()
    assert any("verdict" not in r["runtime"]["serving"] for r in rows), "no recipe to check"
    assert any(r["runtime"]["serving"].get("built") is True for r in rows), "no built image"
    assert any(r["runtime"].get("serving_variants") for r in rows), "no variant to check"
    assert {r["provider_key"]: _problems(r) for r in rows if _problems(r)} == {}


def test_a_drifted_serving_block_is_caught() -> None:
    recipe = next(r for r in _rows() if "served_model_name" in r["runtime"]["serving"])
    cases = {
        "served_model_name": ("served_model_name", recipe["upstream_id"]),
        "@sha256 digest": ("image", "vllm/vllm-openai:v0.33.0"),
        "recipe without image": ("image", None),
    }
    for message, (field, value) in cases.items():
        bad = copy.deepcopy(recipe)
        if value is None:
            del bad["runtime"]["serving"][field]
        else:
            bad["runtime"]["serving"][field] = value
        assert any(message in p for p in _problems(bad)), message
    bad = copy.deepcopy(recipe)
    bad["rollout"]["traffic_percent"] = 5
    assert _problems(bad) == ["traffic_percent is not 0"]


_PROVENANCE = ("source_commit", "workflow_run_id", "package_listing_sha256", "build_log_sha256")


def _unbuilt_row() -> dict[str, Any]:
    """The registry has no unbuilt block now, so one is made by undoing a built one."""
    row = copy.deepcopy(next(r for r in _rows() if r["runtime"]["serving"].get("built") is True))
    serving = row["runtime"]["serving"]
    serving.update(built=False, image=None)
    for field in _PROVENANCE:
        del serving[field]
    serving.pop("not_serving", None)  # a mark on a build goes with the build it marks
    return row


def _built_rows() -> dict[str, dict[str, Any]]:
    return {
        r["runtime"]["serving"]["runner"]: r
        for r in _rows()
        if r["runtime"]["serving"].get("built") is True
    }


# (source commit, run) per slot: C0 and C3 rebuilt by run 44216487886 (WO-D10-0U r3, their
# import gates passed on the CPU runner); C1's job failed in that run, so C1 keeps its first build.
_RUNS = {
    "paddleocr_vl_1_6": ("9754168c92969e17a12c3877c3c0ba44de690918", "44145574050"),
    "mineru": ("b5b349f1897d3f0d34a9ce749e358835d31f44d3", "44216487886"),
    "mineru_vlm": ("b5b349f1897d3f0d34a9ce749e358835d31f44d3", "44216487886"),
}
_MINERU_IMAGE = _ROOT / "infra/runpod/v6/images/mineru-pipeline-akc"


def test_the_three_arena_images_are_built_and_pinned_to_their_run() -> None:
    rows = _built_rows()
    assert set(rows) == set(_RUNS)
    for runner, row in rows.items():
        serving = row["runtime"]["serving"]
        assert (serving["source_commit"], serving["workflow_run_id"]) == _RUNS[runner], runner
        assert serving["enabled"] is False and row["rollout"]["traffic_percent"] == 0, runner
    # The rebuilt C0 and C3 were built from this tree's locks (b5b349f; unchanged since), so
    # their recorded lock digests are those files' digests.
    for runner, fields in {
        "mineru": {"requirements_lock_sha256": "requirements.lock"},
        "mineru_vlm": {
            "requirements_lock_sha256": "requirements.lock",
            "layer_lock_sha256": "requirements-c3.lock",
        },
    }.items():
        serving = rows[runner]["runtime"]["serving"]
        for field, name in fields.items():
            digest = hashlib.sha256((_MINERU_IMAGE / name).read_bytes()).hexdigest()
            assert serving[field] == f"sha256:{digest}", (runner, field)
    # C1 stays evaluation-only: its paddlepaddle-gpu licence file text is uncleared
    assert rows["paddleocr_vl_1_6"]["internal_validation"]["status"] == "candidate_unverified"


def test_a_built_block_needs_a_slot_image_and_its_provenance() -> None:
    rows = _built_rows()
    for runner, row in rows.items():
        assert _problems(row) == [], runner
        serving = row["runtime"]["serving"]
        for field in _PROVENANCE:
            for bad_value in (None, "", 7, "x", "sha256:" + "G" * 64):
                bad = copy.deepcopy(row)
                if bad_value is None:
                    del bad["runtime"]["serving"][field]
                else:
                    bad["runtime"]["serving"][field] = bad_value
                assert f"{field} missing or malformed" in _problems(bad), (runner, field)
        for image in (
            "registry.example/akc:latest",
            "ghcr.io/o/r/x@sha256:" + "0" * 63,  # short digest
            serving["image"] + "\n",  # a trailing newline must not pass
            "docker.io/o/" + serving["image"].split("/", 1)[1],  # not ghcr.io
            None,
            7,
        ):
            bad = copy.deepcopy(row)
            bad["runtime"]["serving"]["image"] = image
            assert "built image is not a digest-pinned ghcr.io reference" in _problems(bad)
        bad = copy.deepcopy(row)
        bad["runtime"]["serving"]["built"] = "true"
        assert "built is not a boolean" in _problems(bad)
    # the class: a built image that is not the block's own slot, in every direction
    images = {k: v["runtime"]["serving"]["image"] for k, v in rows.items()}
    for own in rows:
        for other in rows:
            if own == other:
                continue
            bad = copy.deepcopy(rows[own])
            bad["runtime"]["serving"]["image"] = images[other]
            assert any("image of this block" in p for p in _problems(bad)), (own, other)
    bad = copy.deepcopy(rows["mineru"])  # a shared Dockerfile with no slot named
    del bad["runtime"]["serving"]["image_target"]
    assert any("image of this block" in p for p in _problems(bad))


def test_a_built_image_is_in_this_repositorys_namespace() -> None:
    """The whole name is pinned, not its last component: the same slot under another owner,
    another repository, a deeper or a shallower path is refused, through ``validate`` too."""
    validator = runpy.run_path(str(_ROOT / "infra/model-registry/validate_registry.py"))
    namespace = "ghcr.io/0ssol1620-byte/ai-knowledge-compiler"
    for runner, row in _built_rows().items():
        image = row["runtime"]["serving"]["image"]
        assert image.startswith(namespace + "/arena-"), runner
        name, digest = image.split("@")
        slot = name.rsplit("/", 1)[-1]
        for other in (
            f"ghcr.io/evil/{slot}",
            f"ghcr.io/0ssol1620-byte/other/{slot}",
            f"ghcr.io/evil/ai-knowledge-compiler/{slot}",
            f"{namespace}/extra/{slot}",
            f"ghcr.io/0ssol1620-byte/{slot}",
            f"ghcr.io/{slot}",
        ):
            bad = copy.deepcopy(row)
            bad["runtime"]["serving"]["image"] = f"{other}@{digest}"
            assert any("image of this block" in p for p in _problems(bad)), (runner, other)
    text = _REGISTRY.read_text(encoding="utf-8")
    first = next(iter(_built_rows().values()))["runtime"]["serving"]["image"]
    # every mention of that image, so its not_serving mark moves with it
    bad_text = text.replace(f'"{first}"', '"ghcr.io/evil/' + first.split("/", 3)[3] + '"')
    assert bad_text != text
    validate = validator["validate"]
    original = validate.__globals__["load_yaml"]
    validate.__globals__["load_yaml"] = lambda path: (
        yaml.safe_load(bad_text) if path.name == "models.yaml" else original(path)
    )
    try:
        errors = validate()
    finally:
        validate.__globals__["load_yaml"] = original
    assert len(errors) == 1 and "the image of this block" in errors[0], errors
    assert validator["ARENA_IMAGE_NAMESPACE"] == namespace


def test_the_validator_itself_reports_an_image_named_while_built_is_false() -> None:
    serving = copy.deepcopy(_unbuilt_row()["runtime"]["serving"])
    assert _build_problems(serving) == []
    for image in ("ghcr.io/x@sha256:" + "0" * 64, "", 7):
        serving["image"] = image
        assert _build_problems(serving) == ["image named while built is false"], image


def test_image_target_when_present_is_a_non_empty_string() -> None:
    row = _built_rows()["mineru"]
    assert _problems(row) == []
    for built in (True, False):
        for target in ("", None, 0, 7, False, [], ["c3"], {"t": "c3"}):
            serving = copy.deepcopy(row["runtime"]["serving"])
            serving["image_target"] = target
            if not built:
                serving.update(built=False, image=None)
                for field in _PROVENANCE:
                    del serving[field]
            assert "image_target is not a non-empty string" in _build_problems(serving), (
                built,
                target,
            )
    paddle = _built_rows()["paddleocr_vl_1_6"]["runtime"]["serving"]
    assert "image_target" not in paddle and _build_problems(paddle) == []  # absent is allowed


def test_an_unbuilt_block_names_no_image_and_no_provenance() -> None:
    row = _unbuilt_row()
    assert _problems(row) == []
    row["runtime"]["serving"]["build_log_sha256"] = "sha256:" + "0" * 64
    assert "build_log_sha256 given while built is false" in _problems(row)


def test_the_real_validate_refuses_a_built_block_with_a_broken_field() -> None:
    """Through ``validate`` itself, over the real registry text with one field damaged."""
    validator = runpy.run_path(str(_ROOT / "infra/model-registry/validate_registry.py"))
    validate = validator["validate"]
    assert validate() == []
    text = _REGISTRY.read_text(encoding="utf-8")
    # A recorded value read from the registry, not typed here: a rebuild changes every one.
    value = next(iter(_built_rows().values()))["runtime"]["serving"]["build_log_sha256"]
    bad = text.replace(f'build_log_sha256: "{value}"', f'build_log_sha256: "x{value[7:]}"', 1)
    assert bad != text
    original = validate.__globals__["load_yaml"]

    def patched(path: Path) -> Any:
        return yaml.safe_load(bad) if path.name == "models.yaml" else original(path)

    validate.__globals__["load_yaml"] = patched
    try:
        errors = validate()
    finally:
        validate.__globals__["load_yaml"] = original
    assert any("build_log_sha256 missing or malformed" in e for e in errors), errors


def test_an_image_built_here_needs_its_digest_once_built() -> None:
    """An unbuilt block is allowed exactly as ``image: null`` + ``image_build`` + ``built:
    false``; the public-image rule is unchanged for every other block."""
    row = _unbuilt_row()
    assert _problems(row) == []
    cases: dict[str, tuple[str, Any]] = {
        "recipe without image": ("built", True),
        "image named while built is false": ("image", "registry.example/akc@sha256:" + "0" * 64),
        "image_build is not a Dockerfile": ("image_build", "infra/no/such/Dockerfile"),
        "attested_revision is not the upstream revision": ("attested_revision", "1" * 40),
    }
    for message, (field, value) in cases.items():
        bad = copy.deepcopy(row)
        bad["runtime"]["serving"][field] = value
        assert any(message in p for p in _problems(bad)), message
    built = copy.deepcopy(row)
    built["runtime"]["serving"].update(built=True, image="registry.example/akc:latest")
    assert "image carries no @sha256 digest" in _problems(built)


def test_image_build_names_a_dockerfile_inside_the_repository(tmp_path: Path) -> None:
    """Not any file, and not a Dockerfile reached outside the repository by ``..`` or an
    absolute path."""
    row = _unbuilt_row()
    real = row["runtime"]["serving"]["image_build"]
    outside = tmp_path / "Dockerfile"
    outside.write_text("FROM scratch\n", encoding="utf-8")
    climb = Path(*[".."] * len(_ROOT.parts)) / outside.relative_to(outside.anchor)
    for build in (
        "infra/model-registry/models.yaml",  # an existing file, not a Dockerfile
        "pyproject.toml",
        str(Path(real).parent),  # its directory
        str(outside),  # an absolute path out of the repository
        str(climb),  # ``..`` out of the repository
        "infra/no/such/Dockerfile",
        "",
        None,
        7,
    ):
        bad = copy.deepcopy(row)
        bad["runtime"]["serving"]["image_build"] = build
        assert "image_build is not a Dockerfile in this repository" in _problems(bad), build
    assert _problems(row) == []


def test_not_serving_binds_the_c0_c1_and_c3_digests_and_not_the_next_one() -> None:
    """WO-D10-0U: every recorded arena build stays ``built`` and is marked not to be launched
    (C1, run 44145574050: libgomp and protobuf; C0 and C3, r3: rebuilt by run 44216487886 and
    not yet launched, the lead removes the mark once a page has been served); the mark names
    the exact image, so recording a rebuilt digest without deciding about the mark fails, as
    does a mark without a reason or on an unbuilt block."""
    rows = _built_rows()
    rebuilt_reason = "rebuilt in run 44216487886; not yet launched"
    causes = {
        "mineru": [rebuilt_reason],
        "mineru_vlm": [rebuilt_reason],
        "paddleocr_vl_1_6": ["libgomp", "protobuf 6.33.4", "sentencepiece 0.2.3"],
    }
    # The digests run 44216487886 read back from GHCR (its build-receipt.json per slot).
    namespace = "ghcr.io/0ssol1620-byte/ai-knowledge-compiler/arena-mineru-pipeline-akc"
    images = {
        "mineru": f"{namespace}-c0@sha256:"
        "e89143bcc86d7dc0b2c9e105cf01c0fed85b7801299d2eecb7adc3414f2f615b",
        "mineru_vlm": f"{namespace}-c3@sha256:"
        "00a88750fca76b492ac84cea4e95ae30afb96fe4af041ae7219af6a317debdba",
    }
    marked = {k for k, r in rows.items() if "not_serving" in r["runtime"]["serving"]}
    assert marked == set(causes)  # every recorded build (C1 added by the closing round)
    for runner, image in images.items():
        serving = rows[runner]["runtime"]["serving"]
        assert serving["image"] == image, runner
        assert serving["not_serving"] == {"image": image, "reason": rebuilt_reason}, runner
    for runner in marked:
        row = rows[runner]
        serving = row["runtime"]["serving"]
        assert serving["built"] is True and _problems(row) == [], runner
        assert serving["not_serving"]["image"] == serving["image"], runner
        for cause in causes[runner]:
            assert cause in serving["not_serving"]["reason"], (runner, cause)
        rebuilt = copy.deepcopy(serving)
        rebuilt["image"] = serving["image"].split("@")[0] + "@sha256:" + "a" * 64
        assert _build_problems(rebuilt) == ["not_serving names another image than this block's"]
        for mark in (
            None,
            "do not launch",
            [],
            {"image": serving["image"]},
            {"image": serving["image"], "reason": ""},
            {"image": serving["image"], "reason": "  "},
            {"image": serving["image"], "reason": 7},
            {"image": serving["image"], "reason": "x", "until": "later"},
        ):
            bad = copy.deepcopy(serving)
            bad["not_serving"] = mark
            assert _build_problems(bad) == [
                "not_serving is not exactly an image and a non-empty reason"
            ], (runner, mark)
        unbuilt = copy.deepcopy(serving)
        unbuilt.update(built=False, image=None)
        for field in _PROVENANCE:
            del unbuilt[field]
        assert _build_problems(unbuilt) == ["not_serving given while built is false"], runner


def test_a_drifted_variant_is_caught() -> None:
    row = next(r for r in _rows() if r["runtime"].get("serving_variants"))
    bad = copy.deepcopy(row)
    bad["runtime"]["serving_variants"][0]["image"] = "vllm/vllm-openai:latest"
    assert "image carries no @sha256 digest" in _problems(bad)
