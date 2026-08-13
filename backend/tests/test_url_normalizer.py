import pytest

from app.crawler.url_normalizer import (
    URL_NORMALIZATION_VERSION,
    UrlNormalizationError,
    normalize_url,
)


def test_v1_version_identifier_is_stable() -> None:
    assert URL_NORMALIZATION_VERSION == "url-normalization-v1"


def test_normalizes_host_default_port_dot_segments_tracking_and_query_order() -> None:
    url = normalize_url(
        "HTTP://Example.COM:80/a/../B/?z=2&utm_source=x&a=1#frag",
        drop_query_params=["utm_*"],
    )
    assert url.normalized_url == "http://example.com/B/?a=1&z=2"
    assert url.path == "/B/"


def test_resolves_relative_and_protocol_relative_urls() -> None:
    relative = normalize_url("../about?b=2&a=1", "https://example.com/products/item/")
    protocol = normalize_url("//EXAMPLE.com:443/path", "https://base.test/")
    assert relative.normalized_url == "https://example.com/products/about?a=1&b=2"
    assert protocol.normalized_url == "https://example.com/path"


def test_preserves_trailing_slash_and_path_case() -> None:
    assert normalize_url("https://example.com/Foo/").normalized_url == "https://example.com/Foo/"
    assert normalize_url("https://example.com/Foo").normalized_url == "https://example.com/Foo"


def test_unicode_host_is_idna_encoded() -> None:
    assert normalize_url("https://bücher.example/").host == "xn--bcher-kva.example"


def test_unsupported_scheme_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("javascript:alert(1)")


def test_invalid_host_raises() -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url("https://%/")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "/"),
        ("/a", "/a"),
        ("/a/", "/a/"),
        ("/a/b", "/a/b"),
        ("/a//b", "/a/b"),
        ("/a///b", "/a/b"),
        ("/a/./b", "/a/b"),
        ("/a/../b", "/b"),
        ("/./a", "/a"),
        ("/../a", "/a"),
        ("/a/.", "/a"),
        ("/a/..", "/"),
        ("/a%2Fb", "/a/b"),
        ("/a%2fb", "/a/b"),
        ("/a%5Cb", "/a%5Cb"),
        ("/a%3Fb", "/a%3Fb"),
        ("/a%23b", "/a%23b"),
        ("/a%3Bb", "/a;b"),
        ("/a%40b", "/a@b"),
        ("/a%3Ab", "/a:b"),
        ("/%41", "/A"),
        ("/A", "/A"),
        ("/%7E", "/~"),
        ("/~", "/~"),
        ("/%2E/", "/"),
        ("/./", "/"),
        ("/%2E%2E/", "/"),
        ("/../", "/"),
        ("/%252F", "/%252F"),
        ("/%252E%252E/", "/%252E%252E/"),
        ("/%", "/%25"),
        ("/%25", "/%25"),
        ("/a%20b", "/a%20b"),
        ("/a b", "/a%20b"),
        ("/a+b", "/a+b"),
        ("/café", "/caf%C3%A9"),
        ("/caf%C3%A9", "/caf%C3%A9"),
        ("/Caf%C3%A9", "/Caf%C3%A9"),
        ("/Page", "/Page"),
        ("/page", "/page"),
    ],
)
def test_v1_characterization_path_transformations(path: str, expected: str) -> None:
    assert normalize_url(f"https://example.com{path}").path == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("a=1&b=2", "a=1&b=2"),
        ("b=2&a=1", "a=1&b=2"),
        ("id=1&id=2", "id=1&id=2"),
        ("id=2&id=1", "id=1&id=2"),
        ("id=1&id=1", "id=1&id=1"),
        ("a=", "a="),
        ("a", "a="),
        ("a=1&&b=2", "a=1&b=2"),
        ("q=a%2Fb", "q=a%2Fb"),
        ("q=a/b", "q=a%2Fb"),
        ("q=a%26b", "q=a%26b"),
        ("q=a&b", "b=&q=a"),
        ("q=hello%20world", "q=hello+world"),
        ("q=hello+world", "q=hello+world"),
        ("q=%2B", "q=%2B"),
        ("q=+", "q=+"),
        ("q=%7E", "q=~"),
        ("q=~", "q=~"),
        ("%61=1", "a=1"),
        ("a=1", "a=1"),
        ("x[]=1&x[]=2", "x%5B%5D=1&x%5B%5D=2"),
        ("filter=a&sort=b&filter=c", "filter=a&filter=c&sort=b"),
        ("=value&empty=", "=value&empty="),
    ],
)
def test_v1_characterization_query_transformations(query: str, expected: str) -> None:
    assert normalize_url(f"https://example.com/?{query}").query == expected


def test_v1_characterization_encoded_slash_collapses_with_literal_separator() -> None:
    encoded = normalize_url("https://example.com/a%2Fb").normalized_url
    literal = normalize_url("https://example.com/a/b").normalized_url
    assert encoded == literal


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("?a=1&b=2", "?b=2&a=1"),
        ("?id=1&id=2", "?id=2&id=1"),
        ("?a", "?a="),
        ("?q=hello%20world", "?q=hello+world"),
    ],
)
def test_v1_characterization_query_spellings_collapse(left: str, right: str) -> None:
    assert (
        normalize_url(f"https://example.com/{left}").normalized_url
        == normalize_url(f"https://example.com/{right}").normalized_url
    )


def test_v1_characterization_drop_patterns_are_case_sensitive_and_reencode_survivors() -> None:
    normalized = normalize_url(
        "https://example.com/?z=hello%20world&UTM_source=keep&utm_medium=x&a=1&utm_source=y",
        drop_query_params=["utm_source", "utm_*"],
    )
    assert normalized.query == "UTM_source=keep&a=1&z=hello+world"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "https://example.com/Page/?b=2&a=1",
        "https://xn--bcher-kva.example/caf%C3%A9",
        "https://example.com:8443/a%20b?q=%2B",
    ],
)
def test_v1_characterization_is_idempotent_for_normalized_output(url: str) -> None:
    first = normalize_url(url).normalized_url
    assert normalize_url(first).normalized_url == first


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTP://EXAMPLE.COM/", "http://example.com/"),
        ("http://example.com:80/", "http://example.com/"),
        ("https://example.com:443/", "https://example.com/"),
        ("https://example.com:444/", "https://example.com:444/"),
        ("https://example.com./", "https://example.com./"),
        ("https://127.0.0.1/", "https://127.0.0.1/"),
        ("https://user:password@example.com/", "https://example.com/"),
        ("https://example.com/page#one", "https://example.com/page"),
    ],
)
def test_v1_characterization_authority_and_fragment(raw: str, expected: str) -> None:
    assert normalize_url(raw).normalized_url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "https://[2001:db8::1]/",
        "https://[::ffff:192.0.2.128]/",
    ],
)
def test_v1_characterization_ipv6_literals_are_rejected(raw: str) -> None:
    with pytest.raises(UrlNormalizationError):
        normalize_url(raw)


def test_v1_characterization_unicode_and_punycode_hosts_collapse() -> None:
    unicode_host = normalize_url("https://bücher.example/").normalized_url
    punycode_host = normalize_url("https://xn--bcher-kva.example/").normalized_url
    assert unicode_host == punycode_host


def test_v1_characterization_path_case_and_trailing_slash_remain_distinct() -> None:
    def normalize(value: str) -> str:
        return normalize_url(value).normalized_url

    assert normalize("https://example.com/Page") != normalize("https://example.com/page")
    assert normalize("https://example.com/page") != normalize("https://example.com/page/")
