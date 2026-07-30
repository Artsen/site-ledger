from app.crawler.scope import ScopeConfig, ScopeEngine, techsmith_scope_preset


def test_exact_wildcard_and_excluded_hosts() -> None:
    engine = ScopeEngine(
        ScopeConfig(
            allowed_host_patterns=["example.com", "*.example.com"],
            excluded_host_patterns=["support.*"],
        ),
        "https://example.com/",
    )
    assert engine.evaluate("https://www.example.com/").decision == "crawlable"
    assert engine.evaluate("https://support.example.com/").decision == "excluded_host"
    assert engine.evaluate("https://other.test/").decision == "external"


def test_path_include_and_exclude_prefixes() -> None:
    engine = ScopeEngine(
        ScopeConfig(
            allowed_host_patterns=["example.com"],
            included_path_prefixes=["/docs/"],
            excluded_path_prefixes=["/docs/private/"],
        ),
        "https://example.com/docs/",
    )
    assert engine.evaluate("https://example.com/docs/page").decision == "crawlable"
    assert engine.evaluate("https://example.com/blog/").decision == "excluded_path"
    assert engine.evaluate("https://example.com/docs/private/x").decision == "excluded_path"


def test_already_seen_decision() -> None:
    engine = ScopeEngine(ScopeConfig(allowed_host_patterns=["example.com"]), "https://example.com/")
    assert (
        engine.evaluate("https://example.com/", seen={"https://example.com/"}).decision
        == "already_seen"
    )


def test_techsmith_preset_is_configuration() -> None:
    preset = techsmith_scope_preset()
    assert "techsmith.com" in preset.allowed_host_patterns
    assert "support.*" in preset.excluded_host_patterns
    assert "utm_*" in preset.drop_query_parameters
