from app.services.scan_comparisons import _primary_change_class, _technical_state
from app.services.source_comparison import analyze_source, source_difference_categories


def test_incapsula_cb_only_is_normalization_only() -> None:
    baseline, target = _pair(
        '<main>Same copy</main><script src="/_Incapsula_Resource?'
        'SWJIYLWA=719&ns=4&cb=126305136"></script>',
        '<main>Same copy</main><script src="/_Incapsula_Resource?'
        'SWJIYLWA=719&ns=4&cb=1641872649"></script>',
    )

    categories, details = _categories(baseline, target)

    assert baseline.exact_hash != target.exact_hash
    assert baseline.normalized_source_hash == target.normalized_source_hash
    assert baseline.document_content_hash == target.document_content_hash
    assert categories == ["runtime", "volatile"]
    assert details[0]["rule_id"] == "incapsula_script_src_cb_v1"
    assert _classification(baseline, target, categories) == "normalization_only"


def test_incapsula_and_wordpress_versions_are_technical_not_substantive() -> None:
    baseline, target = _pair(
        _wordpress_page("6.9.5", "126305136"),
        _wordpress_page("6.9.6", "1641872649"),
    )

    categories, _ = _categories(baseline, target)

    assert baseline.normalized_source_hash != target.normalized_source_hash
    assert baseline.document_content_hash == target.document_content_hash
    assert categories == ["dependency", "runtime", "volatile"]
    assert _classification(baseline, target, categories) == "technical_change"


def test_incapsula_and_visible_body_copy_are_substantive() -> None:
    baseline, target = _pair(
        '<main>Before copy</main><script src="/_Incapsula_Resource?cb=1"></script>',
        '<main>After copy</main><script src="/_Incapsula_Resource?cb=2"></script>',
    )

    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert categories == ["document_content", "runtime", "volatile"]
    assert _classification(baseline, target, categories) == "substantive_change"


def test_unknown_generated_json_value_remains_unclassified() -> None:
    baseline, target = _pair(
        '<main>Same copy</main><script type="application/json">'
        '{"f":"a9a3247799b04da69b212c7d80cc975e"}</script>',
        '<main>Same copy</main><script type="application/json">'
        '{"f":"22e52b120ba346129e6937c7a92a44d3"}</script>',
    )

    categories, _ = _categories(baseline, target)

    assert baseline.normalized_source_hash != target.normalized_source_hash
    assert categories == ["unclassified"]
    assert _classification(baseline, target, categories) == "technical_change"


def test_ordinary_script_cb_parameter_is_not_normalized() -> None:
    baseline, target = _pair(
        '<main>Same copy</main><script src="/app.js?cb=1"></script>',
        '<main>Same copy</main><script src="/app.js?cb=2"></script>',
    )

    categories, details = _categories(baseline, target)

    assert baseline.normalized_source_hash != target.normalized_source_hash
    assert categories == ["unclassified"]
    assert details == []
    assert _classification(baseline, target, categories) == "technical_change"


def _pair(baseline: str, target: str):
    before = analyze_source(baseline.encode(), "utf-8")
    after = analyze_source(target.encode(), "utf-8")
    assert before is not None and after is not None
    return before, after


def _categories(baseline, target):
    return source_difference_categories(
        baseline,
        target,
        document_changed=baseline.document_content_hash != target.document_content_hash,
        metadata_changed=False,
    )


def _classification(baseline, target, categories: list[str]) -> str:
    flags = {
        name: False
        for name in (
            "http_status_changed",
            "fetch_state_changed",
            "final_url_changed",
            "redirect_state_changed",
            "content_type_changed",
            "depth_changed",
            "inbound_links_changed",
            "outbound_links_changed",
            "embedded_resources_changed",
            "rendered_state_changed",
            "rendered_counts_changed",
        )
    }
    document_state = (
        "same" if baseline.document_content_hash == target.document_content_hash else "changed"
    )
    normalized_state = (
        "same" if baseline.normalized_source_hash == target.normalized_source_hash else "changed"
    )
    return _primary_change_class(
        presence="observed_in_both",
        exact_source_state="changed",
        normalized_source_state=normalized_state,
        document_content_state=document_state,
        metadata_state="same",
        technical_state=_technical_state(flags, categories, "observed_in_both"),
    )


def _wordpress_page(version: str, cb: str) -> str:
    return (
        '<html><head><meta name="generator" content="WordPress '
        f'{version}" /><link rel="stylesheet" href="/wp-includes/css/main.css?ver={version}">'
        f'</head><body><main>Same copy</main><script src="/wp-includes/js/main.js?'
        f'ver={version}"></script>'
        f'<script src="/_Incapsula_Resource?SWJIYLWA=719&ns=4&cb={cb}"></script></body></html>'
    )
