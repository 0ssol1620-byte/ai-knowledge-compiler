"""C3 MinerU2.5-Pro on vLLM (OpenAI chat): layout, then one recognition call per region.

Step one sends the page, resized to the layout input size, with the layout prompt. Its answer
must be one line per region (a box in 0-1000 page units, a type, optionally a rotation) or the
page is a failure row. Step two sends each region's crop of the page with the prompt for its
type; image regions are not sent (the card's default is ``image_analysis=False``). Every
answer goes through ``vlm.finish``, so its raw bytes are in the receipt before anything parses
them, and a failure in either step is one failure row for the page that keeps every raw answer
received so far. Every call runs inside the shared door and exit (``base.guarded``).

Nothing from mineru-vl-utils is imported or copied. The server loads its logits processor
(``--logits-processors mineru_vl_utils:MinerULogitsProcessor``, image
``infra/runpod/v6/images/mineru25-vllm``); this runner only sends the request argument.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import time
from typing import Any

from PIL import Image

from . import base, vlm
from .base import PROVIDER_CREDENTIAL, RunnerConfig, RunnerUnavailable, guarded
from .openai_chat import _extract
from .vlm import PageRefused, config_sha256, render_settings, require_revision

PROVIDER = "mineru_vlm"
MODEL = "opendatalab/MinerU2.5-Pro-2605-1.2B"
# PyPI mineru-vl-utils 2.0.9 description: "eight 1036x1036 layout inputs".
LAYOUT_SIZE = (1036, 1036)
LAYOUT_PROMPT = "\nLayout Detection:"
REGION_PROMPTS = {
    "table": "\nTable Recognition:",
    "equation": "\nFormula Recognition:",
    "default": "\nText Recognition:",
}
SKIPPED_TYPES = frozenset({"image"})
MAX_REGIONS = 200  # each region is one call: a hostile layout answer cannot fan out further
# Box, ref and rotate tokens are special tokens of this tokenizer (tokenizer_config.json at
# the pin), so they only reach the answer with skip_special_tokens false.
GENERATION: dict[str, Any] = {
    "temperature": 0.01,
    "top_p": 0.001,
    "top_k": 1,
    "max_tokens": 4096,
    "skip_special_tokens": False,
    "vllm_xargs": {"no_repeat_ngram_size": 100},
}
ANGLES = {"up": 0, "right": 90, "down": 180, "left": 270}
PROMPT_SOURCE = (
    "Documented: two-step use and image_analysis=False default (card at bff20d4a); the "
    "server-side MinerULogitsProcessor for no_repeat_ngram_size, 1036x1036 layout input, "
    "block fields type/bbox/angle with angle 0 up, 90 right, 180 down, 270 left (PyPI "
    "mineru-vl-utils 2.0.9 description); temperature 0.01, top_p 0.001, top_k 1 "
    "(generation_config.json at the pin); box/ref/rotate/OTSL tokens are special "
    "(tokenizer_config.json at the pin). UNVERIFIED, not in any document read: the four "
    "prompt texts, the layout line grammar, no_repeat_ngram_size 100, bicubic resize, the "
    "rotation direction of a crop, max_tokens 4096 (generic). Tables come back as OTSL "
    "tokens and are not converted."
)
_LINE = re.compile(
    r"<\|box_start\|>(\d{1,4}) (\d{1,4}) (\d{1,4}) (\d{1,4})<\|box_end\|>"
    r"<\|ref_start\|>([a-z_]{1,32})<\|ref_end\|>(?:<\|rotate_(up|right|down|left)\|>)?"
)

type Region = tuple[tuple[int, int, int, int], str, int]


def config(*, revision: str) -> dict[str, Any]:
    require_revision(revision)
    return {
        "provider": PROVIDER,
        "model": MODEL,
        "served_model_name": f"{MODEL}@{revision}",
        "mode": "two_step",
        "layout_prompt": LAYOUT_PROMPT,
        "layout_input_pixels": list(LAYOUT_SIZE),
        "layout_resample": "bicubic",
        "region_prompts": dict(REGION_PROMPTS),
        "skipped_region_types": sorted(SKIPPED_TYPES),
        "max_regions": MAX_REGIONS,
        "region_rotation": "PIL Image.rotate(angle, expand=True)",
        "prompt_source": PROMPT_SOURCE,
        "generation": json.loads(json.dumps(GENERATION)),
        "server_logits_processor": "mineru_vl_utils:MinerULogitsProcessor (mineru-vl-utils 2.0.9)",
        "content_order": "image_first",
        "input_mode": "page_image_data_url",
        **render_settings(),
    }


def parse_layout(text: str) -> list[Region] | None:
    """The regions of a layout answer, or None when any line is outside the grammar."""
    regions: list[Region] = []
    for line in text.strip().splitlines():
        match = _LINE.fullmatch(line.strip())
        if match is None:
            return None
        x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
        if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
            return None
        regions.append(((x1, y1, x2, y2), match.group(5), ANGLES[match.group(6) or "up"]))
    return regions


def _open_page(data: bytes) -> Image.Image:
    try:
        page = Image.open(io.BytesIO(data))
    except Exception as exc:  # any undecodable page is hostile input: a page refusal
        raise PageRefused("page_image_unreadable") from exc
    if page.width * page.height > vlm.MAX_RENDER_PIXELS:
        raise PageRefused("page_over_pixel_cap")
    try:
        return page.convert("RGB")
    except Exception as exc:
        raise PageRefused("page_image_unreadable") from exc


def _crop(page: Image.Image, box: tuple[int, int, int, int], angle: int) -> Image.Image:
    width, height = page.size
    left, top = math.floor(box[0] * width / 1000), math.floor(box[1] * height / 1000)
    right = max(left + 1, math.ceil(box[2] * width / 1000))
    bottom = max(top + 1, math.ceil(box[3] * height / 1000))
    region = page.crop((left, top, right, bottom))
    return region.rotate(angle, expand=True) if angle else region


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def run(
    case: dict[str, Any], *, endpoint: str | None, revision: str, allow_network: bool = False
) -> dict[str, Any]:
    return guarded(
        PROVIDER_CREDENTIAL,
        endpoint,
        PROVIDER,
        case,
        lambda token: _run(
            case, token, endpoint=endpoint, revision=revision, allow_network=allow_network
        ),
        model_revision=revision,
    )


def _run(
    payload: dict[str, Any],
    token: str | None,
    *,
    endpoint: str | None,
    revision: str,
    allow_network: bool,
) -> dict[str, Any]:
    """Everything after the door; ``guarded`` runs it inside the exit guard."""
    pinned = config(revision=revision)
    served = pinned["served_model_name"]
    run_config = RunnerConfig(PROVIDER, revision, endpoint, allow_network)
    mime, data, render = vlm.page_image(payload)
    page = _open_page(data)
    steps: list[dict[str, Any]] = []
    receipt: dict[str, Any] = {
        **pinned,
        "config_sha256": config_sha256(pinned),
        "model_revision": revision,
        "endpoint": endpoint,
        "image_mime": mime,
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "render": render,
        "steps": steps,
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    extract = _extract(served)
    latency_ms = 0.0

    def call(step: dict[str, Any], image: Image.Image) -> dict[str, Any] | None:
        """One chat call; its receipt is appended to ``steps``. None when it failed."""
        nonlocal latency_ms
        png = _png(image)
        url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        request = {
            "model": served,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": url}},
                        {"type": "text", "text": step["prompt"]},
                    ],
                }
            ],
            **GENERATION,
        }
        body = json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        step = {
            **step,
            "image_sha256": hashlib.sha256(png).hexdigest(),
            "image_pixels": list(image.size),
            "request_sha256": hashlib.sha256(body).hexdigest(),
        }
        started = time.perf_counter()
        status, content_type, raw = base.post_bytes(run_config, body, headers)
        elapsed = (time.perf_counter() - started) * 1000.0
        latency_ms += elapsed
        out = vlm.finish(run_config, payload, step, status, content_type, raw, elapsed, extract)
        if "failure" in out:
            steps.append({**out["receipt"], "failure": out["failure"]["reason"]})
            return None
        steps.append(out["metrics"]["receipt"])
        return out

    def failed(reason: str) -> dict[str, Any]:
        return vlm.failure(run_config, payload, reason, receipt)

    layout = call(
        {"step": "layout", "prompt": LAYOUT_PROMPT},
        page.resize(LAYOUT_SIZE, Image.Resampling.BICUBIC),
    )
    if layout is None:
        return failed("layout_" + steps[-1]["failure"])
    regions = parse_layout(layout["text"])
    if regions is None:
        return failed("layout_unparseable")
    if len(regions) > MAX_REGIONS:
        return failed("layout_too_many_regions")
    texts: list[str] = []
    for index, (box, kind, angle) in enumerate(regions):
        if kind in SKIPPED_TYPES:
            continue
        step = {
            "step": "region",
            "region_index": index,
            "region_type": kind,
            "box": list(box),
            "angle": angle,
            "prompt": REGION_PROMPTS.get(kind, REGION_PROMPTS["default"]),
        }
        try:
            region = call(step, _crop(page, box, angle))
        except RunnerUnavailable:  # nothing came back for this region; step one's bytes stay
            return failed("region_provider_unavailable")
        if region is None:
            return failed("region_" + steps[-1]["failure"])
        texts.append(region["text"])
    if not texts:
        return failed("no_text_regions")
    receipt["revision_attested"] = all(s.get("revision_attested") is True for s in steps)
    return {
        "schema_version": "1.0",
        "benchmark_case_id": payload["benchmark_case_id"],
        "provider": PROVIDER,
        "model_revision": revision,
        "text": "\n\n".join(texts),
        "reading_order": [],
        "blocks": [],
        "generated_claims": [],
        "metrics": {"latency_ms": latency_ms, "receipt": receipt},
        "warnings": [],
    }
