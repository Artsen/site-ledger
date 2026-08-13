from app.performance_benchmark import run_benchmark, run_collection_benchmark


def test_performance_benchmark_fixture_exercises_history_queries() -> None:
    result = run_benchmark(page_count=50, run_count=5, observation_count=100, repetitions=2)

    assert result["fixture"] == {"pages": 50, "runs": 5, "observations": 100}
    assert result["latest_site_query_ms"]["p95"] >= 0
    assert result["page_history_query_ms"]["p95"] >= 0
    assert result["runs_list_query_ms"]["p95"] >= 0


def test_collection_benchmark_persists_the_full_bounded_worklist() -> None:
    result = run_collection_benchmark(page_count=3)

    assert result["provider_requests"] == 14
    assert result["fake_provider_calls"] == 14
    assert result["persisted_observations"] == 14
    assert result["status"] == "completed"
    assert result["final_progress"] == (14, 14)
