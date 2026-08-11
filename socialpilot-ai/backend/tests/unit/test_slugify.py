from __future__ import annotations

from app.utils.slugify import slugify, unique_slug


def test_slugify_basic() -> None:
    assert slugify("Acme Inc") == "acme-inc"


def test_slugify_strips_punctuation() -> None:
    assert slugify("Acme, Inc.!!") == "acme-inc"


def test_slugify_non_latin_collapses_but_does_not_crash() -> None:
    # Arabic org names are a first-class case for this product.
    assert slugify("شركة الذكاء") == ""


def test_unique_slug_falls_back_for_non_latin_names() -> None:
    slug = unique_slug("شركة الذكاء")
    assert slug.startswith("workspace-")


def test_unique_slug_is_actually_unique_across_calls() -> None:
    slugs = {unique_slug("Acme") for _ in range(50)}
    assert len(slugs) == 50
