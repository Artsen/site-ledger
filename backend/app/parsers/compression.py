import gzip
from io import BytesIO


class InvalidGzipError(ValueError):
    pass


class DecompressedResponseTooLargeError(ValueError):
    pass


def maybe_decompress_gzip(
    content: bytes, *, url: str, content_type: str | None, max_decompressed_bytes: int
) -> tuple[bytes, bool]:
    lower_type = (content_type or "").lower()
    looks_gzip = (
        url.lower().endswith(".gz") or "gzip" in lower_type or content.startswith(b"\x1f\x8b")
    )
    if not looks_gzip:
        return content, False
    try:
        with gzip.GzipFile(fileobj=BytesIO(content)) as gzip_file:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = gzip_file.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_decompressed_bytes:
                    raise DecompressedResponseTooLargeError(
                        "Decompressed sitemap exceeded configured response limit"
                    )
                chunks.append(chunk)
    except DecompressedResponseTooLargeError:
        raise
    except OSError as exc:
        raise InvalidGzipError(str(exc)) from exc
    return b"".join(chunks), True
