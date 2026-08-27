import pytest

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


def test_web_content_not_found_diagnostics_are_technical_source_evidence() -> None:
    baseline, target = _pair(
        _web_content_not_found("request-a", "2026-08-07T02:16:00Z"),
        _web_content_not_found("request-b", "2026-08-07T07:21:23Z"),
    )

    categories, _ = _categories(baseline, target)

    assert baseline.exact_hash != target.exact_hash
    assert baseline.normalized_source_hash != target.normalized_source_hash
    assert baseline.document_content_hash == target.document_content_hash
    assert "RequestId : request-a" in baseline.normalized_text
    assert "TimeStamp : 2026-08-07T02:16:00Z" in baseline.normalized_text
    assert categories == ["unclassified"]
    assert _classification(baseline, target, categories) == "technical_change"


def test_web_content_not_found_message_change_is_substantive() -> None:
    baseline, target = _pair(
        _web_content_not_found("request-a", "time-a"),
        _web_content_not_found(
            "request-b", "time-b", message="The requested document does not exist."
        ),
    )

    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert _classification(baseline, target, categories) == "substantive_change"


def test_operational_error_identity_change_is_substantive() -> None:
    baseline, target = _pair(
        _web_content_not_found("request-a", "time-a"),
        _web_content_not_found(
            "request-b",
            "time-b",
            title="AuthenticationFailed",
            status="403",
            error_code="AuthenticationFailed",
        ),
    )

    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert _classification(baseline, target, categories) == "substantive_change"


@pytest.mark.parametrize(
    ("baseline_text", "target_text"),
    [
        ("RequestId: customer-facing-value", "RequestId: another-customer-value"),
        ("TimeStamp: yesterday", "TimeStamp: today"),
        ("Last updated: 2026-08-10", "Last updated: 2026-08-11"),
        ("Order ID: 12345", "Order ID: 67890"),
        ("Build: abcdef123456", "Build: fedcba654321"),
    ],
)
def test_ordinary_dynamic_visible_values_remain_substantive(
    baseline_text: str, target_text: str
) -> None:
    baseline, target = _pair(f"<p>{baseline_text}</p>", f"<p>{target_text}</p>")

    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert _classification(baseline, target, categories) == "substantive_change"


def test_ordinary_404_visible_change_remains_substantive() -> None:
    baseline, target = _pair(
        "<html><head><title>404</title></head><body><h1>Missing page A</h1></body></html>",
        "<html><head><title>404</title></head><body><h1>Missing page B</h1></body></html>",
    )

    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert _classification(baseline, target, categories) == "substantive_change"


def test_webpage_that_mentions_operational_fields_without_exact_structure_is_substantive() -> None:
    baseline, target = _pair(
        "<html><head><title>WebContentNotFound</title></head><body><main>"
        "<h1>The requested content does not exist.</h1><ul>"
        "<li>HttpStatusCode: 404</li><li>ErrorCode: WebContentNotFound</li>"
        "<li>RequestId : request-a</li><li>TimeStamp : time-a</li>"
        "</ul></main></body></html>",
        "<html><head><title>WebContentNotFound</title></head><body><main>"
        "<h1>The requested content does not exist.</h1><ul>"
        "<li>HttpStatusCode: 404</li><li>ErrorCode: WebContentNotFound</li>"
        "<li>RequestId : request-b</li><li>TimeStamp : time-b</li>"
        "</ul></main></body></html>",
    )

    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert _classification(baseline, target, categories) == "substantive_change"


def test_profile_recognition_handles_non_element_dom_nodes() -> None:
    analysis = analyze_source(
        b"<html><head><!-- marker --><title>Ordinary</title></head>"
        b"<body><main>Visible content</main></body></html>",
        "utf-8",
    )

    assert analysis is not None
    assert analysis.document_content_hash is not None


@pytest.mark.parametrize(
    ("baseline_html", "target_html"),
    [
        ("<main>Webinar details</main>", "<main>Page not found</main>"),
        ("<main>Page not found</main>", "<main>Screen Draw webinar</main>"),
        ("<main>Educational video webinar</main>", "<main>Page not found</main>"),
        ("<main>New Camtasia tricks webinar</main>", "<main>Page not found</main>"),
        ("<main>Spotlight and magnify webinar</main>", "<main>Page not found</main>"),
    ],
)
def test_known_substantive_transition_shapes_remain_substantive(
    baseline_html: str, target_html: str
) -> None:
    baseline, target = _pair(baseline_html, target_html)
    categories, _ = _categories(baseline, target)

    assert baseline.document_content_hash != target.document_content_hash
    assert _classification(baseline, target, categories) == "substantive_change"


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


def _web_content_not_found(
    request_id: str,
    timestamp: str,
    *,
    message: str = "The requested content does not exist.",
    title: str = "WebContentNotFound",
    status: str = "404",
    error_code: str = "WebContentNotFound",
) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        f"<title>{title}</title></head><body><h1>{message}</h1><p></p><ul>"
        f"<li>HttpStatusCode: {status}</li><li>ErrorCode: {error_code}</li>"
        f"<li>RequestId : {request_id}</li><li>TimeStamp : {timestamp}</li>"
        "</ul></body></html>"
    )
