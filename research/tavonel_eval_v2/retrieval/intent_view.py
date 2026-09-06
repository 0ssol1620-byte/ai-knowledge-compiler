"""The restricted view a P4e query builder is allowed to see.

Founder ruling, 2026-08-22: **answer independence is verified by information
provenance, not by string matching.** P4d's leakage gate compared query tokens
against body tokens and failed 475 of 522 questions, none of which leaked an
answer span — every one of them "leaked" a word the protocol had explicitly
permitted, which happened to recur in the prose. A question that says
"dependencies" about a section headed "Adding dependencies" is not leaking; it is
asking.

So the check moves upstream. Instead of inspecting the finished string, this
module constrains **what the builder can reach at all**:

* the builder's only argument is an :class:`IntentView`;
* the view carries exactly the five permitted intent sources and nothing else;
* it holds no reference to the document, the atom, the revision or any result,
  so a forbidden field cannot be read through it by any path;
* every field read is recorded with its provenance, and the record is the
  evidence the gate scores.

A lexical overlap figure is still computed downstream, because it is a useful
diagnostic. It is no longer a gate, and calling it one is what this module
exists to stop.
"""

from __future__ import annotations

from typing import Any, Iterator

# --- the permitted intent sources, and only these ----------------------------

TITLE = "document_title"
IDENTITY = "document_identity"
DOC_TYPE = "document_type"
ANCHOR = "anchor_heading"
PARENT = "parent_heading"

PERMITTED_INTENT_SOURCES: tuple[str, ...] = (TITLE, IDENTITY, DOC_TYPE, ANCHOR, PARENT)

#: Named so a violation reports which forbidden source was reached for, rather
#: than only that something was. Nothing here is ever a field of an IntentView;
#: the list exists to make the refusal legible and to be asserted against.
FORBIDDEN_INTENT_SOURCES: tuple[str, ...] = (
    "atom_body",
    "answer_span",
    "oracle_answer",
    "current_revision_id",
    "superseded_revision_id",
    "revision_window",
    "before_after_label",
    "current_superseded_state",
    "retrieval_result",
)


class ForbiddenIntentSource(Exception):
    """Raised when a view is constructed carrying anything not permitted.

    Constructing is where this is caught, not reading. A view that had accepted
    the field and then refused to return it would still be carrying it, and the
    builder's process would still have had it in memory.
    """


class IntentView:
    """Exactly the five permitted fields, with every read recorded.

    ``__slots__`` is not decoration. Without it an attribute could be attached
    to an instance after construction, and the constructor's whitelist would
    stop being the whole story.
    """

    __slots__ = ("_fields", "_reads", "_view_id")

    def __init__(self, view_id: str, **fields: Any) -> None:
        unexpected = sorted(set(fields) - set(PERMITTED_INTENT_SOURCES))
        if unexpected:
            raise ForbiddenIntentSource(
                "an IntentView may carry only " + ", ".join(PERMITTED_INTENT_SOURCES)
                + "; refused: " + ", ".join(unexpected)
            )
        missing = sorted(set(PERMITTED_INTENT_SOURCES) - set(fields) - {PARENT})
        if missing:
            raise ForbiddenIntentSource("an IntentView is incomplete without " + ", ".join(missing))
        object.__setattr__(self, "_view_id", view_id)
        object.__setattr__(self, "_fields", {k: fields[k] for k in fields})
        object.__setattr__(self, "_reads", [])

    # -- reading, with provenance --------------------------------------------

    def read(self, source: str) -> Any:
        """Return a permitted field and record that it was read.

        The record is what the provenance gate scores. A builder that assembled
        a query without going through here would produce fields with no
        provenance, and the gate fails on absence exactly as it fails on a
        forbidden source.
        """
        if source not in PERMITTED_INTENT_SOURCES:
            raise ForbiddenIntentSource("not a permitted intent source: " + source)
        value = self._fields.get(source)
        self._reads.append({"source": source, "value": value})
        return value

    @property
    def view_id(self) -> str:
        return self._view_id

    @property
    def reads(self) -> list[dict[str, Any]]:
        return list(self._reads)

    def provenance(self) -> list[dict[str, Any]]:
        """One record per distinct field the builder actually used."""
        seen: dict[str, dict[str, Any]] = {}
        for record in self._reads:
            if record["value"] is None:
                continue
            seen.setdefault(
                record["source"],
                {
                    "field": record["source"],
                    "provenance": record["source"],
                    "permitted": record["source"] in PERMITTED_INTENT_SOURCES,
                    "value": record["value"],
                },
            )
        return [seen[key] for key in PERMITTED_INTENT_SOURCES if key in seen]

    # -- everything else is closed -------------------------------------------

    def __getattr__(self, name: str) -> Any:
        raise ForbiddenIntentSource(
            "an IntentView exposes no attribute '" + name + "'. Permitted "
            "sources are read through .read()."
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise ForbiddenIntentSource("an IntentView is immutable after construction")

    def __iter__(self) -> Iterator[Any]:
        raise ForbiddenIntentSource("an IntentView is not iterable; read named sources")

    def __repr__(self) -> str:
        return "IntentView(" + self._view_id + ")"


# --- revision neutrality -----------------------------------------------------

INTENT_CHANGED = "INELIGIBLE_INTENT_CHANGED_ACROSS_REVISIONS"


def revision_neutral_fields(
    before: dict[str, Any], after: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """The permitted fields, but only where the two revisions agree.

    If any permitted field differs across the revisions, **no view is built**.
    Taking the current revision's value would let the question carry the answer
    to the very question being asked — which revision is current — through a
    field the protocol calls innocent. Returning the superseded value would be
    the same defect pointing the other way.

    The caller records the second element as the exclusion reason. An external
    intent generated independently of the current/superseded judgement is the
    only admitted alternative, and none exists on this corpus.
    """
    differing = [
        source
        for source in PERMITTED_INTENT_SOURCES
        if before.get(source) != after.get(source)
    ]
    if differing:
        return None, differing
    return {source: after.get(source) for source in PERMITTED_INTENT_SOURCES}, []


# --- the builder -------------------------------------------------------------


def build_query(view: IntentView) -> str:
    """The only query builder P4e uses. Its whole world is ``view``.

    There is deliberately no second parameter. A builder that also received the
    document, the atom or the revision could reach a forbidden source however
    carefully it was written, and the gate would be scoring the author's
    discipline rather than the structure.
    """
    anchor = view.read(ANCHOR)
    parent = view.read(PARENT)
    identity = view.read(IDENTITY)
    doc_type = view.read(DOC_TYPE)
    where = "in the " + doc_type + " for " + identity
    if parent:
        return "what does the section on " + anchor + " under " + parent + " say " + where + "?"
    return "what does the section on " + anchor + " say " + where + "?"
