from app.accessibility_benchmark import run_benchmark


def test_accessibility_benchmark_fixture_exercises_current_and_history_queries() -> None:
    result = run_benchmark(page_count=50, run_count=5, observation_count=100, repetitions=2)

    assert result["fixture"] == {
        "pages": 50,
        "runs": 5,
        "observations": 100,
        "rule_rows": 100,
        "node_rows": 100,
    }
    assert result["latest_page_summary_query_ms"]["p95"] >= 0
    assert result["rule_aggregation_query_ms"]["p95"] >= 0
    assert result["page_history_query_ms"]["p95"] >= 0
    assert result["rule_occurrence_query_ms"]["p95"] >= 0
    assert result["runs_list_query_ms"]["p95"] >= 0
    assert result["sample_payload_gzip_bytes"] < result["sample_payload_raw_bytes"]
