from akc_retrieval.entity_resolution import EntityRecord, resolve_entities


def test_authoritative_registration_conflict_never_auto_merges() -> None:
    left = EntityRecord("a", "Structara Inc.", "110111-000001", "KR", authoritative=True)
    right = EntityRecord("b", "Structara", "110111-999999", "KR")
    decision = resolve_entities(left, right)
    assert decision.disposition == "reject"
    assert decision.reason_codes == ("authoritative_registration_conflict",)


def test_close_multifield_records_merge_with_auditable_score() -> None:
    left = EntityRecord(
        "a", "Structara Co., Ltd.", "110111-000001", "KR", "Seoul Jung-gu 10"
    )
    right = EntityRecord(
        "b", "Structara Co Ltd", "110111-000001", "KR", "Seoul Jung-gu 10"
    )
    decision = resolve_entities(left, right)
    assert decision.disposition == "merge"
    assert decision.log_likelihood_ratio > 4
    assert {name for name, _ in decision.field_similarities} == {
        "name", "registration_id", "jurisdiction", "address"
    }


def test_multilingual_letters_survive_normalization() -> None:
    left = EntityRecord("a", "山东农业信息平台", jurisdiction="CN")
    right = EntityRecord("b", "山東農業信息平台", jurisdiction="CN")
    decision = resolve_entities(left, right, merge_threshold=1.0)
    similarities = dict(decision.field_similarities)
    assert similarities["name"] > 0
    assert similarities["jurisdiction"] == 1
