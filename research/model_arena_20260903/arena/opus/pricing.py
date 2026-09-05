"""API-equivalent list price for a subscription run (masterplan section 22).

The number produced here is a *list-price equivalent*, never an invoice amount
and never ``$0/page``. ``actual_marginal_api_cost`` stays ``"N/A"`` because the
run is included in a Claude Pro/Max subscription.

Cache-token prices are ``null`` in ``price_snapshot.json`` because Anthropic's
fetched sources did not publish them for Opus 5 on 2026-09-03. Rather than
inventing a multiplier, a run that reports cache tokens is marked
``price_complete: false`` and the uncovered token counts are kept on the receipt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.opus.paths import PRICE_SNAPSHOT_PATH, read_json, sha256_tagged


class PriceSnapshotError(RuntimeError):
    """Raised when the price snapshot is missing or unusable."""


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None
    source: str = "unknown"

    def to_json(self) -> dict[str, int | str | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "usage_source": self.source,
        }


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _usage_from(source: Mapping[str, Any], label: str) -> TokenUsage:
    def pick(*names: str) -> int | None:
        for name in names:
            found = _as_int(source.get(name))
            if found is not None:
                return found
        return None

    return TokenUsage(
        input_tokens=pick("input_tokens", "inputTokens", "prompt_tokens"),
        output_tokens=pick("output_tokens", "outputTokens", "completion_tokens"),
        cache_creation_input_tokens=pick(
            "cache_creation_input_tokens", "cacheCreationInputTokens", "cache_creation_tokens"
        ),
        cache_read_input_tokens=pick(
            "cache_read_input_tokens", "cacheReadInputTokens", "cache_read_tokens"
        ),
        source=label,
    )


def extract_usage(payload: Mapping[str, Any], *, model: str | None = None) -> TokenUsage:
    """Token counts for the benchmarked model.

    A Claude Code ``-p`` payload reports usage twice: a top-level ``usage`` block
    and a per-model ``modelUsage`` map. The 2026-09-03 qualification probe showed
    the map carrying an auxiliary Haiku entry beside the Opus entry, so when the
    caller names the model, that model's ``modelUsage`` entry wins and the
    auxiliary tokens are kept out of the benchmark columns. A count that is not
    reported stays ``None``: 0 tokens and "not reported" are different facts.
    """
    model_usage = payload.get("modelUsage")
    if model and isinstance(model_usage, Mapping):
        entry = model_usage.get(model)
        if isinstance(entry, Mapping):
            return _usage_from(entry, f"modelUsage[{model}]")
    usage = payload.get("usage")
    if isinstance(usage, Mapping):
        return _usage_from(usage, "usage")
    if isinstance(model_usage, Mapping):
        for key, entry in model_usage.items():
            if isinstance(entry, Mapping):
                return _usage_from(entry, f"modelUsage[{key}]")
    return TokenUsage(None, None, None, None, source="not_reported")


def auxiliary_usage(payload: Mapping[str, Any], models: Sequence[str]) -> dict[str, Any]:
    """Token counts for models Claude Code used on its own behalf, recorded but not scored."""
    model_usage = payload.get("modelUsage")
    out: dict[str, Any] = {}
    if not isinstance(model_usage, Mapping):
        return out
    for name in models:
        entry = model_usage.get(name)
        if isinstance(entry, Mapping):
            out[name] = _usage_from(entry, f"modelUsage[{name}]").to_json()
    return out


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    model_id: str
    captured_at: str
    source_urls: tuple[str, ...]
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    cache_write_per_mtok_usd: float | None
    cache_read_per_mtok_usd: float | None
    snapshot_sha256: str

    @classmethod
    def load(cls, path: Path | None = None) -> PriceSnapshot:
        target = path or PRICE_SNAPSHOT_PATH
        if not target.is_file():
            raise PriceSnapshotError(f"price snapshot missing: {target}")
        raw = target.read_bytes()
        data = read_json(target)
        if not isinstance(data, dict):
            raise PriceSnapshotError(f"price snapshot is not an object: {target}")
        prices = data.get("prices")
        if not isinstance(prices, dict):
            raise PriceSnapshotError(f"price snapshot has no 'prices' object: {target}")
        try:
            input_price = float(prices["input_per_mtok_usd"])
            output_price = float(prices["output_per_mtok_usd"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceSnapshotError(
                f"price snapshot lacks usable input/output prices: {target}"
            ) from exc
        cache_write = prices.get("cache_write_per_mtok_usd")
        cache_read = prices.get("cache_read_per_mtok_usd")
        urls = data.get("source_urls")
        return cls(
            model_id=str(data.get("model_id", "")),
            captured_at=str(data.get("captured_at", "")),
            source_urls=tuple(str(u) for u in urls) if isinstance(urls, list) else (),
            input_per_mtok_usd=input_price,
            output_per_mtok_usd=output_price,
            cache_write_per_mtok_usd=float(cache_write) if isinstance(cache_write, (int, float))
            else None,
            cache_read_per_mtok_usd=float(cache_read) if isinstance(cache_read, (int, float))
            else None,
            snapshot_sha256=sha256_tagged(raw),
        )


@dataclass(frozen=True, slots=True)
class PriceEstimate:
    api_equivalent_list_price_usd: float | None
    price_complete: bool
    uncovered: tuple[str, ...]
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "api_equivalent_list_price_usd": self.api_equivalent_list_price_usd,
            "api_equivalent_price_complete": self.price_complete,
            "api_equivalent_price_uncovered_components": list(self.uncovered),
            "api_equivalent_price_notes": list(self.notes),
        }


def estimate_price(usage: TokenUsage, snapshot: PriceSnapshot) -> PriceEstimate:
    """List-price equivalent for one page.

    Returns ``None`` for the price when neither input nor output tokens were
    reported: a page whose usage is unknown has an unknown price, and writing 0.0
    there would be inventing data.
    """
    notes: list[str] = [
        "List-price equivalent for a run billed to a Claude subscription; "
        "not an invoice amount (masterplan section 22).",
    ]
    uncovered: list[str] = []
    if usage.input_tokens is None and usage.output_tokens is None:
        return PriceEstimate(
            api_equivalent_list_price_usd=None,
            price_complete=False,
            uncovered=("input_tokens", "output_tokens"),
            notes=(*notes, "Payload reported no token usage; price is unknown, not zero."),
        )

    total = 0.0
    if usage.input_tokens is None:
        uncovered.append("input_tokens")
    else:
        total += usage.input_tokens / 1_000_000 * snapshot.input_per_mtok_usd
    if usage.output_tokens is None:
        uncovered.append("output_tokens")
    else:
        total += usage.output_tokens / 1_000_000 * snapshot.output_per_mtok_usd

    if usage.cache_creation_input_tokens:
        if snapshot.cache_write_per_mtok_usd is None:
            uncovered.append("cache_creation_input_tokens")
            notes.append(
                "Cache-write price is not published in the snapshot; those tokens are "
                "excluded from the estimate rather than priced by assumption."
            )
        else:
            total += (
                usage.cache_creation_input_tokens
                / 1_000_000
                * snapshot.cache_write_per_mtok_usd
            )
    if usage.cache_read_input_tokens:
        if snapshot.cache_read_per_mtok_usd is None:
            uncovered.append("cache_read_input_tokens")
            notes.append(
                "Cache-read price is not published in the snapshot; those tokens are "
                "excluded from the estimate rather than priced by assumption."
            )
        else:
            total += (
                usage.cache_read_input_tokens / 1_000_000 * snapshot.cache_read_per_mtok_usd
            )

    return PriceEstimate(
        api_equivalent_list_price_usd=round(total, 8),
        price_complete=not uncovered,
        uncovered=tuple(uncovered),
        notes=tuple(notes),
    )


__all__ = [
    "PriceEstimate",
    "PriceSnapshot",
    "PriceSnapshotError",
    "TokenUsage",
    "auxiliary_usage",
    "estimate_price",
    "extract_usage",
]
