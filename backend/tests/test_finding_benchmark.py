from app.finding_benchmark import run_benchmark


def test_finding_evaluation_topology_loading_is_set_based() -> None:
    report = run_benchmark(page_count=120, links_per_page=5)
    assert report["page_count"] == 120
    assert report["resource_occurrence_count"] == 600
    assert report["detector_count"] == 11
    assert report["outcome_count"] == 1_320
    assert report["select_count"] <= 10
