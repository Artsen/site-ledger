from app.performance_benchmark import run_benchmark


def test_performance_benchmark_fixture_exercises_history_queries() -> None:
    result = run_benchmark(page_count=50, run_count=5, observation_count=100, repetitions=2)

    assert result["fixture"] == {"pages": 50, "runs": 5, "observations": 100}
    assert result["latest_site_query_ms"]["p95"] >= 0
    assert result["page_history_query_ms"]["p95"] >= 0
    assert result["runs_list_query_ms"]["p95"] >= 0
