from __future__ import annotations

import datetime as dt
import re
import unicodedata


def slugify(text: str, max_length: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_length].strip("-") or "untitled"


def unique_slug(session, model, text: str, prefix: str = "", max_length: int = 80) -> str:
    """A slug that is not already taken for ``model``."""
    base = slugify(f"{prefix}-{text}" if prefix else text, max_length)
    candidate, n = base, 2
    while session.query(model.id).filter(model.slug == candidate).first():
        suffix = f"-{n}"
        candidate = base[: max_length - len(suffix)] + suffix
        n += 1
    return candidate


def dated_slug(text: str, when: dt.date, max_length: int = 80) -> str:
    return slugify(f"{when.isoformat()}-{text}", max_length)
