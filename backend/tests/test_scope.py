from app.crawler.scope import ScopeConfig, ScopeEngine


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


def test_empty_allowed_hosts_derive_exact_starting_hostname() -> None:
    engine = ScopeEngine(ScopeConfig(), "https://www.example.com/")
    assert engine.evaluate("https://www.example.com/about").decision == "crawlable"
    assert engine.evaluate("https://example.com/").decision == "external"
    assert engine.evaluate("https://blog.example.com/").decision == "external"


def test_subdomain_allowed_when_follow_subdomains_enabled() -> None:
    engine = ScopeEngine(
        ScopeConfig(allowed_host_patterns=["example.com"], follow_subdomains=True),
        "https://example.com/",
    )
    assert engine.evaluate("https://blog.example.com/").decision == "crawlable"


def test_explicit_wildcard_host_patterns_still_work() -> None:
    engine = ScopeEngine(
        ScopeConfig(allowed_host_patterns=["*.example.com"], follow_subdomains=False),
        "https://www.example.com/",
    )
    assert engine.evaluate("https://blog.example.com/").decision == "crawlable"
