from typing import Literal

GROUP_KEYS = {"marketing", "customer_education", "rs", "other"}
PLATFORM_KEYS = {"wordpress_root", "wordpress_learn", "rs_managed", "other"}
OWNERSHIP_KEYS = {"web_team", "customer_education", "rs", "shared", "unknown"}

GroupKey = Literal["marketing", "customer_education", "rs", "other"]
PlatformKey = Literal["wordpress_root", "wordpress_learn", "rs_managed", "other"]
OwnershipKey = Literal["web_team", "customer_education", "rs", "shared", "unknown"]


def is_valid_group_key(value: str) -> bool:
    return value in GROUP_KEYS


def is_valid_platform_key(value: str) -> bool:
    return value in PLATFORM_KEYS


def is_valid_ownership_key(value: str) -> bool:
    return value in OWNERSHIP_KEYS
