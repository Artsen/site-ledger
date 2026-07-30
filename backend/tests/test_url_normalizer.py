import pytest

from app.crawler.url_normalizer import UrlNormalizationError, normalize_url


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
