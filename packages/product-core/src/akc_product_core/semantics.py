"""Deterministic, evidence-bound semantic projection for Product-Core v2.

The projection deliberately separates extraction from adjudication. Rule-derived
entities and relations remain warning-level knowledge, while contradiction
candidates always require review instead of becoming asserted truth.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

Language = Literal["en", "ko", "ja", "zh", "mixed", "und"]
Polarity = Literal["positive", "negative"]
Modality = Literal["asserted", "normative", "uncertain", "reported"]

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。\uff01\uff1f])\s+|[\r\n]+")
_TOKEN = re.compile(
    r"[A-Za-z][A-Za-z0-9._+-]*|[가-힣]{2,}|[\u3040-\u30ff]{2,}|[\u4e00-\u9fff]{2,}|\d+(?:[.,]\d+)*"
)
_NUMBER = re.compile(
    r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?:\s?(?:%|원|억원|만원|달러|USD|KRW|million|billion))?",
    re.IGNORECASE,
)
_QUESTION_END = re.compile(r"[?\uff1f]\s*$")
_ENGLISH_PREDICATE = re.compile(
    r"\b(?:is|are|was|were|be|been|has|have|had|does|do|did|will|would|shall|"
    r"should|must|approved|published|reported|shows?|demonstrates?|requires?|"
    r"prohibits?|contains?|uses?|achieves?|supports?|causes?|improves?|reduces?|"
    r"increased|decreased)\b",
    re.IGNORECASE,
)
_CJK_PREDICATE_ENDING = re.compile(
    r"(?:이다|입니다|있다|없다|한다|했다|된다|됐다|하였다|보였다|나타났다|"
    r"발표했다|증가했다|감소했다|해야|다|する|した|である|です|ます|"
    r"是|为|有|无|显示|表明|增长|下降|必须|应当)$"
)
_METADATA_FRAGMENT = re.compile(
    r"^\s*[\"'{[(]*\s*(?:page|pages|page_number|pageno|bbox|bbox1000|x|y|"
    r"width|height|section|table|figure|fig)\s*[\"']*\s*[:=#]?\s*"
    r"[-+]?\d+(?:[.,]\d+)*(?:\s*[,}\])]+)?\s*$",
    re.IGNORECASE,
)
_NON_CONTRADICTION_TOPICS = frozenset(
    {
        "page",
        "pages",
        "page number",
        "pageno",
        "section",
        "table",
        "figure",
        "fig",
        "chapter",
        "appendix",
        "index",
        "version",
        "revision",
    }
)
_DATE_PATTERNS = (
    re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b"),
    re.compile(r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])\b"),
    re.compile(r"\b(?:19|20)\d{2}\b"),
    re.compile(r"(?:19|20)\d{2}년\s*(?:1[0-2]|0?[1-9])?월?\s*(?:3[01]|[12]\d|0?[1-9])?일?"),
)
_TITLE_ENTITY = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.-]{1,})(?:\s+(?:[A-Z][A-Za-z0-9&.-]{1,})){1,4}\b"
)
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9-]{1,11}\b")
_KOREAN_ORGANIZATION = re.compile(
    r"(?:[가-힣A-Za-z0-9]+(?:주식회사|대학교|연구원|위원회|법원|은행|공사|재단|협회|부|청))"
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
        "및",
        "그",
        "그리고",
        "대한",
        "되는",
        "에서",
        "으로",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "と",
        "の",
        "は",
        "が",
        "を",
        "に",
        "で",
        "了",
        "的",
        "是",
        "在",
        "和",
    }
)
_KOREAN_PARTICLES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "부터",
    "처럼",
    "보다",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "와",
    "과",
    "의",
    "에",
    "도",
    "만",
)
_NEGATION = (
    " not ",
    " no ",
    " never ",
    "without",
    "cannot",
    "can't",
    "doesn't",
    "didn't",
    "아니다",
    "않",
    "없",
    "못",
    "禁止",
    "ない",
    "不是",
    "没有",
    "不得",
)
_NORMATIVE = (
    " must ",
    " shall ",
    " required",
    "prohibited",
    "해야",
    "하여야",
    "금지",
    "필수",
    "なければなら",
    "禁止",
    "必须",
    "应当",
    "不得",
)
_UNCERTAIN = (
    " may ",
    " might ",
    " could ",
    "likely",
    "estimate",
    "forecast",
    "possible",
    "가능",
    "추정",
    "예상",
    "전망",
    "수 있다",
    "可能",
    "预计",
    "推定",
)
_REPORTED = (
    "according to",
    "reported",
    "announced",
    "stated",
    "밝혔",
    "보고",
    "발표",
    "によると",
    "発表",
    "据",
    "报告",
    "宣布",
)
_AUTHORITY_TIERS: tuple[tuple[frozenset[str], str, float], ...] = (
    (
        frozenset(
            {"regulatory_filing", "statute", "court_record", "official", "authority_verified"}
        ),
        "official",
        1.0,
    ),
    (frozenset({"peer_reviewed", "academic", "standard"}), "reviewed", 0.85),
    (frozenset({"contract", "policy", "internal_approved"}), "controlled", 0.7),
    (frozenset({"informal", "web", "user_supplied"}), "informal", 0.4),
    (frozenset({"unclassified"}), "unclassified", 0.0),
)
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "finance": (
        "revenue",
        "income",
        "asset",
        "liability",
        "filing",
        "매출",
        "영업이익",
        "재무",
        "공시",
        "資産",
        "收入",
    ),
    "legal": (
        "agreement",
        "contract",
        "clause",
        "party",
        "liability",
        "계약",
        "조항",
        "당사자",
        "의무",
        "契約",
        "合同",
    ),
    "research": (
        "abstract",
        "method",
        "dataset",
        "experiment",
        "citation",
        "초록",
        "방법론",
        "실험",
        "연구",
        "論文",
        "研究",
    ),
    "technical": (
        "api",
        "architecture",
        "component",
        "procedure",
        "requirement",
        "오류",
        "아키텍처",
        "구성요소",
        "기술",
        "仕様",
        "接口",
    ),
    "course": (
        "lecture",
        "syllabus",
        "assignment",
        "lesson",
        "강의",
        "교재",
        "과제",
        "講義",
        "课程",
    ),
    "personal": (
        "meeting note",
        "diary",
        "journal",
        "memo",
        "회의록",
        "일기",
        "메모",
        "日記",
        "备忘",
    ),
}
_DOMAIN_OBJECT_TYPES: dict[str, tuple[str, ...]] = {
    "finance": ("company", "filing", "statement", "metric", "risk"),
    "legal": ("contract", "party", "clause", "obligation", "date"),
    "research": ("paper", "author", "method", "dataset", "finding"),
    "technical": ("product", "component", "procedure", "requirement", "issue"),
    "course": ("course", "module", "concept", "assignment", "resource"),
    "personal": ("note", "person", "topic", "task", "event"),
    "mixed": ("document", "note", "entity", "relation", "claim"),
}


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(f"{len(part)}:{part}" for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _normalized_space(value: str) -> str:
    return " ".join(value.split())


def detect_language(value: str) -> Language:
    counts = {
        "en": len(re.findall(r"[A-Za-z]", value)),
        "ko": len(re.findall(r"[가-힣]", value)),
        "ja": len(re.findall(r"[\u3040-\u30ff]", value)),
        "zh": len(re.findall(r"[\u4e00-\u9fff]", value)),
    }
    nonzero = sorted(
        ((count, language) for language, count in counts.items() if count), reverse=True
    )
    if not nonzero:
        return "und"
    total = sum(count for count, _ in nonzero)
    if len(nonzero) > 1 and nonzero[1][0] / total >= 0.2:
        return "mixed"
    return nonzero[0][1]  # type: ignore[return-value]


def _sentences(value: str) -> tuple[str, ...]:
    rows = tuple(
        sentence
        for sentence in (
            _normalized_space(item).strip("-•· \t") for item in _SENTENCE_BOUNDARY.split(value)
        )
        if len(sentence) >= 3 and any(character.isalnum() for character in sentence)
    )
    return rows or ((_normalized_space(value),) if value.strip() else ())


def _is_semantic_claim_candidate(value: str) -> bool:
    """Keep OCR provenance intact while rejecting index-like semantic projections."""

    normalized = _normalized_space(value).strip()
    if sum(character.isalpha() for character in normalized) < 2:
        return False
    if re.match(r"[a-z]", normalized):
        return False
    if _METADATA_FRAGMENT.fullmatch(normalized):
        return False
    if re.fullmatch(r"https?://\S+", normalized, re.IGNORECASE):
        return False
    if _QUESTION_END.search(normalized):
        return False
    if _ENGLISH_PREDICATE.search(normalized):
        return True
    # Unfinished OCR lines remain available as evidence-bound retrieval chunks. They
    # do not become asserted graph claims merely because they are long.
    return bool(_CJK_PREDICATE_ENDING.search(normalized.rstrip(".!?\u3002\uff01\uff1f")))


def _tokens(value: str) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in _TOKEN.findall(value):
        token = raw.casefold()
        if re.fullmatch(r"[가-힣]{3,}", token):
            for particle in _KOREAN_PARTICLES:
                if token.endswith(particle) and len(token) - len(particle) >= 2:
                    token = token[: -len(particle)]
                    break
        normalized.append(token)
    return tuple(normalized)


def semantic_tokens(value: str) -> tuple[str, ...]:
    """Return the versioned script-aware lexical units used by semantic retrieval."""

    return tuple(token for token in _tokens(value) if token not in _STOPWORDS)


def _temporal_refs(value: str) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in _DATE_PATTERNS:
        found.extend(_normalized_space(match.group(0)) for match in pattern.finditer(value))
    return tuple(dict.fromkeys(found))


def _modality(value: str) -> Modality:
    lowered = f" {value.casefold()} "
    if any(marker in lowered for marker in _NORMATIVE):
        return "normative"
    if any(marker in lowered for marker in _UNCERTAIN):
        return "uncertain"
    if any(marker in lowered for marker in _REPORTED):
        return "reported"
    return "asserted"


def _polarity(value: str) -> Polarity:
    lowered = f" {value.casefold()} "
    return "negative" if any(marker in lowered for marker in _NEGATION) else "positive"


def authority_tier(authority: str) -> tuple[str, float]:
    normalized = authority.casefold().strip()
    for aliases, tier, score in _AUTHORITY_TIERS:
        if normalized in aliases:
            return tier, score
    return "informal", 0.25


def _entity_candidates(value: str) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    rows.extend((match.group(0), "organization") for match in _KOREAN_ORGANIZATION.finditer(value))
    rows.extend((match.group(0), "named_entity") for match in _TITLE_ENTITY.finditer(value))
    rows.extend((match.group(0), "acronym") for match in _ACRONYM.finditer(value))
    deduplicated: dict[str, tuple[str, str]] = {}
    for label, entity_type in rows:
        canonical = _normalized_space(label).strip(".,;:()[]{}")
        if len(canonical) < 2:
            continue
        deduplicated.setdefault(canonical.casefold(), (canonical, entity_type))
    return tuple(deduplicated[key] for key in sorted(deduplicated))


def _topic_key(value: str) -> str:
    without_dates = value
    for pattern in _DATE_PATTERNS:
        without_dates = pattern.sub(" ", without_dates)
    without_numbers = _NUMBER.sub(" ", without_dates)
    tokens = [token for token in _tokens(without_numbers) if token not in _STOPWORDS]
    return " ".join(tokens[:12])


@dataclass(frozen=True, slots=True)
class SemanticSource:
    logical_id: str
    source_id: str
    source_version_id: str
    evidence_id: str
    text: str
    authority: str


@dataclass(frozen=True, slots=True)
class SemanticEntity:
    entity_id: str
    canonical_name: str
    entity_type: str
    claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "entityId": self.entity_id,
            "canonicalName": self.canonical_name,
            "entityType": self.entity_type,
            "claimIds": list(self.claim_ids),
            "evidenceIds": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class SemanticClaim:
    claim_id: str
    logical_id: str
    source_id: str
    source_version_id: str
    evidence_id: str
    text: str
    language: Language
    polarity: Polarity
    modality: Modality
    authority: str
    authority_tier: str
    authority_score: float
    temporal_refs: tuple[str, ...]
    numeric_values: tuple[str, ...]
    entity_ids: tuple[str, ...]
    topic_key: str
    retrieval_terms: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "claimId": self.claim_id,
            "logicalId": self.logical_id,
            "sourceId": self.source_id,
            "sourceVersionId": self.source_version_id,
            "evidenceId": self.evidence_id,
            "text": self.text,
            "language": self.language,
            "polarity": self.polarity,
            "modality": self.modality,
            "authority": self.authority,
            "authorityTier": self.authority_tier,
            "authorityScore": self.authority_score,
            "temporalRefs": list(self.temporal_refs),
            "numericValues": list(self.numeric_values),
            "entityIds": list(self.entity_ids),
            "topicKey": self.topic_key,
            "retrievalTerms": list(self.retrieval_terms),
        }


@dataclass(frozen=True, slots=True)
class SemanticRelation:
    relation_id: str
    subject_id: str
    predicate: Literal["mentions"]
    object_id: str
    evidence_id: str

    def as_record(self) -> dict[str, str]:
        return {
            "relationId": self.relation_id,
            "subjectId": self.subject_id,
            "predicate": self.predicate,
            "objectId": self.object_id,
            "evidenceId": self.evidence_id,
        }


@dataclass(frozen=True, slots=True)
class ContradictionCandidate:
    contradiction_id: str
    claim_ids: tuple[str, str]
    topic_key: str
    reason: Literal["numeric_disagreement", "polarity_disagreement"]
    temporal_refs: tuple[str, ...]

    def as_record(self) -> dict[str, object]:
        return {
            "contradictionId": self.contradiction_id,
            "claimIds": list(self.claim_ids),
            "topicKey": self.topic_key,
            "reason": self.reason,
            "temporalRefs": list(self.temporal_refs),
            "adjudication": "human_review_required",
        }


@dataclass(frozen=True, slots=True)
class SemanticCompilation:
    domain: str
    object_types: tuple[str, ...]
    languages: tuple[tuple[str, int], ...]
    temporal_structure: str
    claims: tuple[SemanticClaim, ...]
    entities: tuple[SemanticEntity, ...]
    relations: tuple[SemanticRelation, ...]
    contradictions: tuple[ContradictionCandidate, ...]
    retrieval_profile: dict[str, object]

    def profile_record(self) -> dict[str, object]:
        return {
            "schemaVersion": "tavonel.semantic_profile.v1",
            "domain": self.domain,
            "objectTypes": list(self.object_types),
            "languages": dict(self.languages),
            "temporalStructure": self.temporal_structure,
            "claimCount": len(self.claims),
            "entityCount": len(self.entities),
            "relationCount": len(self.relations),
            "contradictionCandidateCount": len(self.contradictions),
            "retrieval": self.retrieval_profile,
        }


def _domain(sources: tuple[SemanticSource, ...]) -> str:
    corpus = " ".join(source.text.casefold() for source in sources)
    scores = {
        domain: sum(corpus.count(keyword.casefold()) for keyword in keywords)
        for domain, keywords in _DOMAIN_KEYWORDS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if not ranked or ranked[0][1] == 0:
        return "mixed"
    if len(ranked) > 1 and ranked[1][1] > 0 and ranked[1][1] >= ranked[0][1] * 0.7:
        return "mixed"
    return ranked[0][0]


def _retrieval_profile(
    *,
    claims: tuple[SemanticClaim, ...],
    entities: tuple[SemanticEntity, ...],
    languages: Counter[str],
) -> dict[str, object]:
    multilingual = (
        len([language for language, count in languages.items() if count and language != "und"]) > 1
    )
    graph_density = len(entities) / max(1, len(claims))
    lexical = 0.40 if multilingual else 0.35
    graph = 0.20 if graph_density >= 0.5 else 0.15
    authority = 0.10
    vector = round(1.0 - lexical - graph - authority, 2)
    return {
        "schemaVersion": "tavonel.adaptive_hybrid_profile.v1",
        "weights": {
            "vector": vector,
            "lexical": lexical,
            "graph": graph,
            "authority": authority,
        },
        "vectorMaterialization": "external_embedding_provider_required",
        "materializedSignals": ["multilingual_lexical", "entity_graph", "authority_prior"],
        "tokenization": "unicode-script-aware-v1",
        "candidateK": 40 if multilingual else 30,
        "topK": 8,
    }


def compile_semantics(sources: tuple[SemanticSource, ...]) -> SemanticCompilation:
    claim_rows: list[dict[str, object]] = []
    entity_mentions: defaultdict[str, list[tuple[str, str, str]]] = defaultdict(list)
    languages: Counter[str] = Counter()
    for source in sources:
        tier, authority_score = authority_tier(source.authority)
        for index, sentence in enumerate(_sentences(source.text)):
            if not _is_semantic_claim_candidate(sentence):
                continue
            language = detect_language(sentence)
            languages[language] += 1
            claim_id = _stable_id("claim", source.logical_id, str(index), sentence.casefold())
            entity_candidates = _entity_candidates(sentence)
            entity_ids = tuple(
                _stable_id("entity", label.casefold()) for label, _ in entity_candidates
            )
            for (label, entity_type), entity_id in zip(entity_candidates, entity_ids, strict=True):
                entity_mentions[entity_id].append((label, entity_type, claim_id))
            claim_rows.append(
                {
                    "claim_id": claim_id,
                    "logical_id": source.logical_id,
                    "source_id": source.source_id,
                    "source_version_id": source.source_version_id,
                    "evidence_id": source.evidence_id,
                    "text": sentence,
                    "language": language,
                    "polarity": _polarity(sentence),
                    "modality": _modality(sentence),
                    "authority": source.authority,
                    "authority_tier": tier,
                    "authority_score": authority_score,
                    "temporal_refs": _temporal_refs(sentence),
                    "numeric_values": tuple(
                        match.group(0).strip() for match in _NUMBER.finditer(sentence)
                    ),
                    "entity_ids": entity_ids,
                    "topic_key": _topic_key(sentence),
                    "retrieval_terms": tuple(
                        dict.fromkeys(
                            token for token in _tokens(sentence) if token not in _STOPWORDS
                        )
                    ),
                }
            )
    claims = tuple(SemanticClaim(**row) for row in claim_rows)  # type: ignore[arg-type]
    claim_by_id = {claim.claim_id: claim for claim in claims}
    semantic_entities = tuple(
        SemanticEntity(
            entity_id=entity_id,
            canonical_name=mentions[0][0],
            entity_type=mentions[0][1],
            claim_ids=tuple(dict.fromkeys(item[2] for item in mentions)),
            evidence_ids=tuple(
                dict.fromkeys(claim_by_id[item[2]].evidence_id for item in mentions)
            ),
        )
        for entity_id, mentions in sorted(entity_mentions.items())
    )
    relations = tuple(
        SemanticRelation(
            relation_id=_stable_id("relation", claim.claim_id, "mentions", entity_id),
            subject_id=claim.claim_id,
            predicate="mentions",
            object_id=entity_id,
            evidence_id=claim.evidence_id,
        )
        for claim in claims
        for entity_id in claim.entity_ids
    )
    grouped: defaultdict[tuple[str, tuple[str, ...]], list[SemanticClaim]] = defaultdict(list)
    for claim in claims:
        if claim.topic_key and claim.topic_key not in _NON_CONTRADICTION_TOPICS:
            grouped[(claim.topic_key, claim.temporal_refs)].append(claim)
    contradiction_rows: dict[str, ContradictionCandidate] = {}
    for (topic_key, temporal_refs), group in grouped.items():
        for left_index, left in enumerate(group):
            for right in group[left_index + 1 :]:
                reason: Literal["numeric_disagreement", "polarity_disagreement"] | None = None
                if (
                    left.numeric_values
                    and right.numeric_values
                    and left.numeric_values != right.numeric_values
                ):
                    reason = "numeric_disagreement"
                elif left.polarity != right.polarity:
                    reason = "polarity_disagreement"
                if reason is None:
                    continue
                claim_ids = (
                    min(left.claim_id, right.claim_id),
                    max(left.claim_id, right.claim_id),
                )
                contradiction_id = _stable_id("contradiction", *claim_ids, reason)
                contradiction_rows[contradiction_id] = ContradictionCandidate(
                    contradiction_id=contradiction_id,
                    claim_ids=claim_ids,
                    topic_key=topic_key,
                    reason=reason,
                    temporal_refs=temporal_refs,
                )
    domain = _domain(sources)
    contradictions = tuple(contradiction_rows[key] for key in sorted(contradiction_rows))
    return SemanticCompilation(
        domain=domain,
        object_types=_DOMAIN_OBJECT_TYPES[domain],
        languages=tuple(sorted(languages.items())),
        temporal_structure=(
            "explicit" if any(claim.temporal_refs for claim in claims) else "undated"
        ),
        claims=claims,
        entities=semantic_entities,
        relations=relations,
        contradictions=contradictions,
        retrieval_profile=_retrieval_profile(
            claims=claims,
            entities=semantic_entities,
            languages=languages,
        ),
    )


__all__ = [
    "ContradictionCandidate",
    "SemanticClaim",
    "SemanticCompilation",
    "SemanticEntity",
    "SemanticRelation",
    "SemanticSource",
    "authority_tier",
    "compile_semantics",
    "detect_language",
    "semantic_tokens",
]
