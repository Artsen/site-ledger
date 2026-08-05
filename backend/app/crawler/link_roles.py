from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

DOWNLOAD_EXTENSIONS = frozenset(
    {
        "7z",
        "apk",
        "csv",
        "dmg",
        "doc",
        "docx",
        "exe",
        "mov",
        "mp3",
        "mp4",
        "msi",
        "pdf",
        "pkg",
        "ppt",
        "pptx",
        "rar",
        "wav",
        "xls",
        "xlsx",
        "zip",
    }
)
LINK_ROLE_LABELS = {
    "email": "Email",
    "telephone": "Telephone",
    "download": "Download",
    "breadcrumb": "Breadcrumb",
    "navigation": "Navigation",
    "main_content": "Main content",
    "footer": "Footer",
    "sidebar": "Sidebar",
    "header_utility": "Header utility",
    "image": "Image",
    "unknown": "Unknown",
}


@dataclass(frozen=True)
class LinkRoleResult:
    role: str
    rule: str
    context: dict[str, Any]


def classify_link_role(anchor: Any, resolved_url: str | None) -> LinkRoleResult:
    raw_href = str(anchor.get("href") or "")
    scheme = urlsplit(raw_href).scheme.casefold()
    ancestors = [node for node in anchor.iterancestors() if isinstance(node.tag, str)]
    landmark = next((node for node in ancestors if _is_landmark(node)), None)
    aria_label = _attribute(landmark, "aria-label") if landmark is not None else None
    role = _attribute(landmark, "role") if landmark is not None else None
    tag = landmark.tag.lower() if landmark is not None else None
    has_image = bool(anchor.xpath(".//img"))
    visible_text = " ".join(anchor.text_content().split())
    accessible_text = (
        visible_text or _attribute(anchor, "aria-label") or _attribute(anchor, "title")
    )
    extension = _path_extension(resolved_url)
    context = {
        "nearest_landmark_tag": tag,
        "nearest_landmark_role": role,
        "landmark_aria_label": aria_label,
        "has_image": has_image,
        "has_visible_text": bool(visible_text),
        "has_accessible_text": bool(accessible_text),
        "has_download_attribute": anchor.get("download") is not None,
        "resolved_path_extension": extension,
    }
    if scheme == "mailto":
        return LinkRoleResult("email", "href_mailto", context)
    if scheme == "tel":
        return LinkRoleResult("telephone", "href_tel", context)
    if anchor.get("download") is not None:
        return LinkRoleResult("download", "download_attribute", context)
    if extension in DOWNLOAD_EXTENSIONS:
        return LinkRoleResult("download", "download_extension", context)
    if any(_is_breadcrumb(node) for node in ancestors):
        return LinkRoleResult("breadcrumb", "landmark_breadcrumb", context)
    if any(_tag_or_role(node, "footer", "contentinfo") for node in ancestors):
        return LinkRoleResult("footer", "ancestor_footer", context)
    if any(_tag_or_role(node, "aside", "complementary") for node in ancestors):
        return LinkRoleResult("sidebar", "ancestor_aside", context)
    if any(_tag_or_role(node, "main", "main") for node in ancestors):
        return LinkRoleResult("main_content", "ancestor_main", context)
    if any(_tag_or_role(node, "nav", "navigation") for node in ancestors):
        return LinkRoleResult("navigation", "ancestor_nav", context)
    if any(_tag_or_role(node, "header", "banner") for node in ancestors):
        return LinkRoleResult("header_utility", "ancestor_header", context)
    if has_image and not accessible_text:
        return LinkRoleResult("image", "image_only", context)
    return LinkRoleResult("unknown", "fallback_unknown", context)


def _is_landmark(node: Any) -> bool:
    return node.tag.lower() in {"nav", "header", "footer", "main", "aside"} or (
        _attribute(node, "role") in {"navigation", "banner", "contentinfo", "main", "complementary"}
    )


def _is_breadcrumb(node: Any) -> bool:
    label = (_attribute(node, "aria-label") or "").casefold()
    classes = (_attribute(node, "class") or "").casefold().replace("_", "-").split()
    itemtype = (_attribute(node, "itemtype") or "").casefold()
    return (
        "breadcrumb" in label
        or any("breadcrumb" in token for token in classes)
        or ("breadcrumblist" in itemtype)
    )


def _tag_or_role(node: Any, tag: str, role: str) -> bool:
    return node.tag.lower() == tag or _attribute(node, "role") == role


def _attribute(node: Any, name: str) -> str | None:
    value = node.get(name)
    return str(value).strip().casefold() if value is not None and str(value).strip() else None


def _path_extension(url: str | None) -> str | None:
    if not url:
        return None
    segment = urlsplit(url).path.rsplit("/", 1)[-1]
    if "." not in segment:
        return None
    return segment.rsplit(".", 1)[-1].casefold()
