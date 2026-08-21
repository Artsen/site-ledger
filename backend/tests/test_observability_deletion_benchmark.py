from app.observability_deletion_benchmark import run_benchmark


def test_observability_deletion_benchmark_exercises_all_lifecycle_operations() -> None:
    result = run_benchmark(
        list_run_count=10,
        list_observation_count=100,
        performance_observation_count=20,
        accessibility_observation_count=20,
    )

    assert result["fixture"]["performance_delete_observations"] == 20
    assert result["fixture"]["accessibility_rule_rows"] == 20
    assert result["performance_run_list_ms"] >= 0
    assert result["accessibility_run_list_ms"] >= 0
    assert result["performance_preview_ms"] >= 0
    assert result["performance_delete_ms"] >= 0
    assert result["accessibility_preview_ms"] >= 0
    assert result["accessibility_delete_ms"] >= 0
    assert result["payload_gc_ms"] >= 0
    assert result["peak_traced_python_bytes"] > 0
