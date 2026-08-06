from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

RESOURCE_KIND_LABELS = {
    "html_page": "HTML Page",
    "image": "Image",
    "document": "Document",
    "stylesheet": "Stylesheet",
    "script": "Script",
    "font": "Font",
    "video": "Video",
    "audio": "Audio",
    "archive": "Archive",
    "feed": "Feed",
    "manifest": "Manifest",
    "structured_data": "Structured data",
    "other": "Other",
    "unknown": "Unknown",
}

HTML_MIME_TYPES = {"text/html", "application/xhtml+xml"}
DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "application/msword",
    "application/rtf",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.presentation",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/csv",
}
SCRIPT_MIME_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/x-ecmascript",
    "application/x-javascript",
    "text/ecmascript",
    "text/javascript",
}
FONT_MIME_TYPES = {
    "application/font-sfnt",
    "application/font-woff",
    "application/vnd.ms-fontobject",
    "application/x-font-opentype",
    "application/x-font-ttf",
    "font/collection",
    "font/otf",
    "font/sfnt",
    "font/ttf",
    "font/woff",
    "font/woff2",
}
ARCHIVE_MIME_TYPES = {
    "application/gzip",
    "application/java-archive",
    "application/vnd.android.package-archive",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/x-rar-compressed",
    "application/x-tar",
    "application/zip",
}
FEED_MIME_TYPES = {"application/atom+xml", "application/rss+xml"}
MANIFEST_MIME_TYPES = {"application/manifest+json", "application/x-web-app-manifest+json"}
STRUCTURED_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "text/xml",
}

EXTENSION_KINDS = {
    **{
        ext: "image"
        for ext in ("avif", "bmp", "gif", "ico", "jpeg", "jpg", "png", "svg", "tif", "tiff", "webp")
    },
    **{
        ext: "document"
        for ext in (
            "csv",
            "doc",
            "docx",
            "odf",
            "odp",
            "ods",
            "odt",
            "pdf",
            "ppt",
            "pptx",
            "rtf",
            "txt",
            "xls",
            "xlsx",
        )
    },
    "css": "stylesheet",
    **{ext: "script" for ext in ("cjs", "js", "mjs")},
    **{ext: "font" for ext in ("eot", "otf", "ttf", "woff", "woff2")},
    **{ext: "video" for ext in ("avi", "m4v", "mkv", "mov", "mp4", "webm")},
    **{ext: "audio" for ext in ("aac", "flac", "m4a", "mp3", "oga", "ogg", "wav")},
    **{ext: "archive" for ext in ("7z", "apk", "bz2", "gz", "jar", "rar", "tar", "tgz", "zip")},
    **{ext: "feed" for ext in ("atom", "rss")},
    "webmanifest": "manifest",
    **{ext: "structured_data" for ext in ("json", "jsonld", "xml")},
    **{ext: "html_page" for ext in ("htm", "html", "xhtml")},
}


@dataclass(frozen=True)
class ResourceClassification:
    kind: str
    rule: str
    normalized_mime_type: str | None
    file_extension: str | None
    content_disposition_filename: str | None = None

    @property
    def is_html(self) -> bool:
        return self.kind == "html_page"


def normalized_mime_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    value = content_type.split(";", 1)[0].strip().casefold()
    return value or None


def file_extension(url: str | None) -> str | None:
    if not url:
        return None
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    if "." not in name or name.endswith("."):
        return None
    extension = name.rsplit(".", 1)[-1].casefold()
    return extension[:32] if re.fullmatch(r"[a-z0-9][a-z0-9+_-]*", extension) else None


def content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    encoded = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", value, re.IGNORECASE)
    quoted = re.search(r'filename\s*=\s*"([^"\r\n]+)"', value, re.IGNORECASE)
    plain = re.search(r"filename\s*=\s*([^;\r\n]+)", value, re.IGNORECASE)
    raw = (
        encoded.group(1)
        if encoded
        else quoted.group(1)
        if quoted
        else plain.group(1)
        if plain
        else ""
    )
    cleaned = unquote(raw).strip().replace("\x00", "")
    cleaned = "".join(
        character for character in cleaned if character >= " " and character != "\x7f"
    )
    return cleaned[:255] or None


def classify_response(
    *,
    url: str | None,
    content_type: str | None,
    content_disposition: str | None = None,
    prefix: bytes = b"",
) -> ResourceClassification:
    mime = normalized_mime_type(content_type)
    extension = file_extension(url)
    filename = content_disposition_filename(content_disposition)
    mime_result = _kind_from_mime(mime)
    if mime_result:
        kind, rule = mime_result
        return ResourceClassification(kind, rule, mime, extension, filename)
    if filename:
        filename_kind = EXTENSION_KINDS.get(file_extension(filename) or "")
        if filename_kind:
            return ResourceClassification(
                filename_kind, "content_disposition_filename", mime, extension, filename
            )
    signature = _kind_from_signature(prefix)
    if signature:
        kind, rule = signature
        return ResourceClassification(kind, rule, mime, extension, filename)
    if extension and extension in EXTENSION_KINDS:
        return ResourceClassification(
            EXTENSION_KINDS[extension], "extension", mime, extension, filename
        )
    return ResourceClassification(
        "other" if mime else "unknown", "fallback_unknown", mime, extension, filename
    )


def classify_reference(
    *,
    url: str | None,
    element_tag: str,
    attribute_name: str,
    rel: str | None = None,
    as_hint: str | None = None,
) -> ResourceClassification:
    extension = file_extension(url)
    tag = element_tag.casefold()
    attribute = attribute_name.casefold()
    rel_tokens = set((rel or "").casefold().split())
    hint = (as_hint or "").casefold()
    context: tuple[str, str] | None = None
    if tag in {"img", "picture", "input"} or attribute == "poster":
        context = ("image", "element_img")
    elif tag == "script":
        context = ("script", "element_script")
    elif "stylesheet" in rel_tokens:
        context = ("stylesheet", "element_stylesheet")
    elif tag == "link" and "manifest" in rel_tokens:
        context = ("manifest", "element_manifest")
    elif tag == "link" and hint == "font":
        context = ("font", "element_font_preload")
    elif tag == "link" and hint in {"image", "script", "style", "video", "audio"}:
        context = ({"style": "stylesheet"}.get(hint, hint), f"element_{hint}")
    elif tag in {"video", "track"}:
        context = ("video", "element_video")
    elif tag == "audio":
        context = ("audio", "element_audio")
    elif tag == "source":
        context = ((EXTENSION_KINDS.get(extension or "") or "other"), "element_source")
    elif tag in {"object", "embed"}:
        context = ((EXTENSION_KINDS.get(extension or "") or "other"), "element_embed")
    elif tag == "link" and rel_tokens.intersection({"icon", "apple-touch-icon", "mask-icon"}):
        context = ("image", "element_img")
    if context:
        return ResourceClassification(context[0], context[1], None, extension)
    if extension and extension in EXTENSION_KINDS:
        return ResourceClassification(EXTENSION_KINDS[extension], "extension", None, extension)
    return ResourceClassification("unknown", "fallback_unknown", None, extension)


def _kind_from_mime(mime: str | None) -> tuple[str, str] | None:
    if mime in HTML_MIME_TYPES:
        return "html_page", "mime_text_html"
    if mime and mime.startswith("image/"):
        return "image", "mime_image"
    if mime == "application/pdf":
        return "document", "mime_pdf"
    if mime in DOCUMENT_MIME_TYPES:
        return "document", "mime_document"
    if mime == "text/css":
        return "stylesheet", "mime_stylesheet"
    if mime in SCRIPT_MIME_TYPES:
        return "script", "mime_javascript"
    if mime in FONT_MIME_TYPES or (mime and mime.startswith("font/")):
        return "font", "mime_font"
    if mime and mime.startswith("video/"):
        return "video", "mime_video"
    if mime and mime.startswith("audio/"):
        return "audio", "mime_audio"
    if mime in ARCHIVE_MIME_TYPES:
        return "archive", "mime_archive"
    if mime in FEED_MIME_TYPES:
        return "feed", "mime_feed"
    if mime in MANIFEST_MIME_TYPES:
        return "manifest", "mime_manifest"
    if mime in STRUCTURED_MIME_TYPES or (mime and mime.endswith("+json")):
        return "structured_data", "mime_structured_data"
    return None


def _kind_from_signature(prefix: bytes) -> tuple[str, str] | None:
    stripped = prefix.lstrip()
    lower = stripped[:512].lower()
    if lower.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "html_page", "signature_html"
    if prefix.startswith(b"%PDF-"):
        return "document", "signature_pdf"
    if prefix.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")) or (
        prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP"
    ):
        return "image", "signature_image"
    if prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08", b"\x1f\x8b")):
        return "archive", "signature_archive"
    return None
