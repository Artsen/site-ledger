MAX_CLASSIFICATION_LENGTH = 64


def normalize_classification(value: str, *, fallback: str) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        return fallback
    if len(normalized) > MAX_CLASSIFICATION_LENGTH:
        raise ValueError(
            f"Classification values must be {MAX_CLASSIFICATION_LENGTH} characters or fewer."
        )
    return normalized
