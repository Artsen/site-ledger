from app import scan_projections


def test_build_and_verify_commands(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        scan_projections,
        "_build",
        lambda scan_id, force: calls.append((scan_id, force)) or True,
    )
    monkeypatch.setattr(scan_projections, "_verify", lambda scan_id: scan_id == 12)

    assert scan_projections.main(["build", "11"]) == 0
    assert scan_projections.main(["rebuild", "12"]) == 0
    assert scan_projections.main(["verify", "12"]) == 0
    assert calls == [(11, False), (12, True)]


def test_build_missing_honors_limit_and_continues_after_failure(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        scan_projections,
        "_missing_scan_ids",
        lambda limit: [1, 2, 3][:limit],
    )

    def build(scan_id: int, *, force: bool) -> bool:
        calls.append(scan_id)
        return scan_id != 2

    monkeypatch.setattr(scan_projections, "_build", build)

    assert scan_projections.main(["build-missing", "--limit", "3"]) == 1
    assert calls == [1, 2, 3]


def test_build_missing_can_stop_after_failure(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(scan_projections, "_missing_scan_ids", lambda limit: [1, 2, 3])
    monkeypatch.setattr(
        scan_projections,
        "_build",
        lambda scan_id, force: calls.append(scan_id) or scan_id != 2,
    )

    assert scan_projections.main(["build-missing", "--stop-on-error"]) == 1
    assert calls == [1, 2]
