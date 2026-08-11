from app.structured_content_benchmark import run_benchmark


def test_structured_content_benchmark_fixture_preserves_reuse_and_determinism() -> None:
    result = run_benchmark(observation_count=20, unique_blob_count=15)

    assert result["fixture"]["observations"] == 20
    assert result["fixture"]["unique_blobs"] == 15
    assert result["fixture"]["reused_observations"] == 5
    assert result["fixture"]["artifacts"] == 15
    assert result["deterministic_rebuild_equivalence"] is True
