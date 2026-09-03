from app.finding_benchmark import run_benchmark


def test_finding_evaluation_topology_loading_is_set_based() -> None:
    report = run_benchmark(page_count=120, links_per_page=5)
    assert report["page_count"] == 120
    assert report["resource_occurrence_count"] == 600
    assert report["source_count"] == 3
    assert report["source_entry_observation_count"] == 192
    assert report["detector_count"] == 14
    assert report["outcome_count"] == 1_680
    assert report["evidence_manifest_bytes"] > 0
    assert report["select_count"] <= 15
