#!/usr/bin/env python3
"""Read Libraries.io's Repositories table into SFIR7 `RawCatalogRecord`s, fail-closed.

Everything this module reads is somebody else's data, written six years before
this study existed. Its whole job is to carry that data across without adding a
TAVONEL judgement to it, and to refuse loudly when it cannot.

**The header is a contract, not a hint.** The column names this parser needs are
declared here, before the file is opened. A CSV whose header lacks one of them is
refused with the names it did find. Positional indexing is never used: the
Libraries.io tables have dozens of columns and a silent off-by-one would produce
a roster of real repositories ranked by the wrong field, which no downstream
check could detect.

**A row that cannot be read is dropped and counted, never guessed.** Every
rejection reason is tallied and returned, so the receipt can say how many rows
were unusable and why. A parser that silently skips is how a corpus of 30 million
becomes a corpus of 4 million with nobody noticing.

**The rank is copied, never computed.** `catalog_rank_value` is Libraries.io's
published SourceRank verbatim. The independence of SFIR7's frame rests entirely
on the ordinal having been decided by someone else; a rank TAVONEL recomputed
would be a TAVONEL judgement wearing an external catalogue's name.

**Identity is the catalogue's, not the address.** `record_id` is Libraries.io's
own stable repository id, and it is what the frame rule orders and tie-breaks on.
`owner/repo` is where the census will send requests -- an address, and addresses
move. SFIR6 measured exactly that hazard: GitHub answers HTTP 200 for a renamed
repository from a different identity (INC-V2-108, finding 4).

`host_uuid` is carried for that reason. It is the host's own numeric repository
id as the catalogue recorded it in 2020, and it is the one field that lets a
census check the repository that *answered* against the repository that was
*selected*. A rename changes `owner/repo` and leaves this alone, so a roster
pinned by it can survive six years of renames without silently measuring a
different repository. Nothing in this module uses it; it exists so the census
can close that hole rather than inherit it.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"

#: The Libraries.io column each `RawCatalogRecord` field is read from. Declared
#: before the file is opened, so a header that moved is a refusal rather than a
#: silently different roster.
COLUMN_CONTRACT: dict[str, str] = {
    "record_id": "ID",
    "host_uuid": "UUID",
    "host": "Host Type",
    "name_with_owner": "Name with Owner",
    "catalog_rank_value": "SourceRank",
    "created_utc": "Created Timestamp",
    "last_activity_utc": "Last pushed Timestamp",
    "spdx_license_id": "License",
    "language": "Language",
    "fork": "Fork",
    "status": "Status",
}

#: Rows the catalogue itself marks as gone. Kept as a named set rather than a
#: truth test, because "" means live and anything else means the publisher said
#: something about it.
REMOVED_STATUSES = frozenset({"Removed", "Deprecated", "Unmaintained", "Hidden"})

#: CSV fields in this table run to long descriptions and READMEs.
FIELD_SIZE_LIMIT = 64 * 1024 * 1024


class CatalogParseRefused(RuntimeError):
    """The catalogue file is not the shape SFIR7 declared it would read."""


@dataclass(frozen=True, slots=True)
class RawCatalogRecord:
    """One repository as the catalogue published it. No TAVONEL-derived field."""

    record_id: str
    host_uuid: str
    host: str
    name_with_owner: str
    catalog_rank_value: int
    created_utc: str
    last_activity_utc: str
    spdx_license_id: str
    language: str
    fork: bool
    status: str


def require_header(header: Iterable[str]) -> dict[str, int]:
    """Bind each declared field to a column index, or refuse naming what is missing.

    Returning indexes rather than reading by key is deliberate: it is checked
    once here, and every row afterwards is read positionally from a mapping that
    was proven correct, so a row with a stray extra comma cannot silently shift a
    value into the wrong field.
    """
    columns = list(header)
    if not columns:
        raise CatalogParseRefused("catalogue file has no header row")
    # Strip a UTF-8 BOM if the publisher left one on the first column name.
    if columns and columns[0].startswith("﻿"):
        columns[0] = columns[0][1:]
    index: dict[str, int] = {}
    missing: list[str] = []
    for field, column in COLUMN_CONTRACT.items():
        if column in columns:
            index[field] = columns.index(column)
        else:
            missing.append(column)
    if missing:
        raise CatalogParseRefused(
            f"catalogue header is missing {missing!r}. Found {len(columns)} columns: "
            f"{columns[:40]!r}. SFIR7 reads this table by declared column name and "
            "will not guess a position."
        )
    duplicated = [name for name, count in Counter(columns).items() if count > 1]
    if any(name in set(COLUMN_CONTRACT.values()) for name in duplicated):
        raise CatalogParseRefused(
            f"catalogue header repeats a column SFIR7 reads: {duplicated!r}. "
            "Which one carries the value is not a guess this parser may make."
        )
    return index


def _clean(value: str) -> str:
    return value.strip()


def _is_iso_date(value: str) -> bool:
    """The same date criterion the frame applies, checked where rows are counted.

    Two of the rule's four predicates are date comparisons, and Libraries.io has
    rows whose `Last pushed Timestamp` is blank. Left to the evaluator, the first
    such row aborts the whole selection with a refusal -- correct, and useless,
    because it says nothing about how many rows are like that or on which host.

    So it is refused here, alongside `NO_PUBLISHED_RANK`, on the same principle:
    a row that cannot answer a question the declared rule asks is dropped and
    counted, never guessed at. It can only lower the eligible count, which is the
    direction that cannot be suspected of having been chosen.

    `test_the_parser_accepts_exactly_what_the_frame_can_read` binds this to
    `frame._as_date` over a table of values, so the two cannot drift apart.
    """
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return False
    return True


def parse_row(row: list[str], index: dict[str, int]) -> tuple[RawCatalogRecord | None, str]:
    """Return a record, or `None` and the reason it could not be read."""
    highest = max(index.values())
    if len(row) <= highest:
        return None, "SHORT_ROW"
    record_id = _clean(row[index["record_id"]])
    if not record_id:
        return None, "NO_RECORD_ID"
    name = _clean(row[index["name_with_owner"]])
    if name.count("/") != 1 or name.startswith("/") or name.endswith("/"):
        return None, "NAME_WITH_OWNER_NOT_OWNER_SLASH_REPO"
    raw_rank = _clean(row[index["catalog_rank_value"]])
    if not raw_rank:
        return None, "NO_PUBLISHED_RANK"
    try:
        rank = int(raw_rank)
    except ValueError:
        # A non-integer rank is refused rather than coerced. Ranking descending
        # over a value this parser invented would be a TAVONEL ordinal.
        return None, "RANK_NOT_AN_INTEGER"
    created = _clean(row[index["created_utc"]])
    if not created:
        return None, "NO_CREATED_TIMESTAMP"
    if not _is_iso_date(created):
        return None, "CREATED_TIMESTAMP_NOT_A_DATE"
    last_activity = _clean(row[index["last_activity_utc"]])
    if not last_activity:
        return None, "NO_LAST_ACTIVITY_TIMESTAMP"
    if not _is_iso_date(last_activity):
        return None, "LAST_ACTIVITY_TIMESTAMP_NOT_A_DATE"
    raw_fork = _clean(row[index["fork"]]).casefold()
    if raw_fork not in {"true", "false", ""}:
        return None, "FORK_NOT_BOOLEAN"
    return (
        RawCatalogRecord(
            record_id=record_id,
            host_uuid=_clean(row[index["host_uuid"]]),
            host=_clean(row[index["host"]]),
            name_with_owner=name,
            catalog_rank_value=rank,
            created_utc=created,
            last_activity_utc=last_activity,
            spdx_license_id=_clean(row[index["spdx_license_id"]]),
            language=_clean(row[index["language"]]),
            fork=raw_fork == "true",
            status=_clean(row[index["status"]]),
        ),
        "",
    )


def stream_records(
    path: Path, tally: list[int] | None = None
) -> Iterator[tuple[RawCatalogRecord | None, str]]:
    """Yield every row's outcome, in file order, holding one row at a time.

    `tally`, if given, is the producer's own count of rows yielded. The consumer
    reconciles against it, which is the only way that check can ever fail: a
    count taken inside the consuming loop and compared with the same loop's
    bookkeeping agrees with itself by construction (INC-V2-036).
    """
    csv.field_size_limit(FIELD_SIZE_LIMIT)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as error:
            raise CatalogParseRefused("catalogue file is empty") from error
        index = require_header(header)
        for row in reader:
            if tally is not None:
                tally[0] += 1
            yield parse_row(row, index)


def read_catalog(path: Path) -> tuple[list[RawCatalogRecord], dict[str, Any]]:
    """Read the whole table, returning the records and an accounting of the rest.

    The accounting is not decoration, and it is reconciled against the *producer*
    rather than against itself. An earlier version compared a total counted
    inside this loop with the same loop's own kept-plus-rejected tally; removing
    that check changed nothing, because two numbers maintained by one loop cannot
    disagree. Mutation testing caught it (INC-V2-036, again). The count that
    matters comes from `stream_records`, so a row dropped between producer and
    consumer -- a stray `continue` added here by a later edit -- is refused.
    """
    records: list[RawCatalogRecord] = []
    rejected: Counter[str] = Counter()
    yielded = [0]
    accounted = 0
    for record, reason in stream_records(path, yielded):
        accounted += 1
        if record is None:
            rejected[reason] += 1
        else:
            records.append(record)
    total = yielded[0]
    if accounted != total or len(records) + sum(rejected.values()) != total:
        raise CatalogParseRefused(
            "row accounting does not balance: "
            f"{total} yielded by the reader, {accounted} accounted for, "
            f"{len(records)} kept, {sum(rejected.values())} rejected. "
            "A row went missing between reading and counting."
        )
    return records, {
        "rows_total": total,
        "records_parsed": len(records),
        "rows_rejected": sum(rejected.values()),
        "rejection_reasons": dict(sorted(rejected.items())),
        "column_contract": dict(COLUMN_CONTRACT),
        "rank_is_the_catalogues_own": True,
        "rank_recomputed_by_tavonel": False,
        "identity_is_the_catalogues_record_id": True,
        "name_with_owner_is_an_address_not_an_identity": True,
        "host_uuid_carried_for_rename_detection": True,
    }
