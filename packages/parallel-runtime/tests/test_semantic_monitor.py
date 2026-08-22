from akc_parallel_runtime.semantic_monitor import SemanticDriftMonitor, SemanticSample


def test_monitor_tracks_strata_and_detects_sustained_semantic_drift() -> None:
    monitor = SemanticDriftMonitor(
        ewma_alpha=0.5,
        degraded_threshold=0.10,
        quarantine_threshold=0.25,
    )
    first = monitor.observe(SemanticSample("tables", True, 0.01))
    assert first.state == "healthy"
    monitor.observe(SemanticSample("tables", False, 0.6))
    final = monitor.observe(SemanticSample("formulas", False, 0.6))
    assert final.state == "quarantined"
    assert {item.stratum for item in final.strata} == {"tables", "formulas"}


def test_monitor_is_deterministic_for_same_sequence() -> None:
    sequence = [
        SemanticSample("text", True, 0.02),
        SemanticSample("text", False, 0.2),
        SemanticSample("table", True, 0.03),
    ]
    monitors = [SemanticDriftMonitor(), SemanticDriftMonitor()]
    projections = []
    for monitor in monitors:
        for item in sequence:
            projection = monitor.observe(item)
        projections.append(projection)
    assert projections[0] == projections[1]
