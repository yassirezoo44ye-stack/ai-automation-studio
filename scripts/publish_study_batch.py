"""Publish three reviewed PDFs to Flow; no Payhip browser automation.

Usage: python scripts/publish_study_batch.py /path/to/batch.json
Environment: STUDY_LIBRARY_BASE_URL, STUDY_LIBRARY_PUBLISH_KEY.
The manifest holds relative filenames; all files must remain beside/below it.
"""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx


def read_batch(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) != 3:
        raise ValueError("A daily batch must contain exactly three lessons")
    seen = set()
    root = path.resolve().parent
    for item in data:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) and item[k].strip()
            for k in ("slug", "title", "subject", "description", "pdf", "cover")
        ):
            raise ValueError(
                "Each lesson needs slug, title, subject, description, pdf and cover"
            )
        if item["slug"] in seen:
            raise ValueError("Duplicate lesson slug in batch")
        seen.add(item["slug"])
        for key in ("pdf", "cover"):
            f = (root / item[key]).resolve()
            if not f.is_relative_to(root) or not f.is_file():
                raise ValueError("Batch files must exist under the manifest directory")
            item[key] = f
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    base = os.getenv("STUDY_LIBRARY_BASE_URL", "").rstrip("/")
    key = os.getenv("STUDY_LIBRARY_PUBLISH_KEY", "")
    parsed = urlparse(base)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http"
                and parsed.hostname in ("localhost", "127.0.0.1")
            )
        )
    ):
        parser.error(
            "Set STUDY_LIBRARY_BASE_URL to your Flow HTTPS origin (localhost HTTP is allowed)"
        )
    if len(key) < 32:
        parser.error("Set a STUDY_LIBRARY_PUBLISH_KEY of at least 32 characters")
    batch = read_batch(args.manifest)
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        for item in batch:
            with item["pdf"].open("rb") as pdf, item["cover"].open("rb") as cover:
                res = client.post(
                    base + "/api/study-library/lessons",
                    headers={"X-Study-Publish-Key": key},
                    data={
                        k: item[k] for k in ("slug", "title", "subject", "description")
                    },
                    files={
                        "pdf": ("lesson.pdf", pdf, "application/pdf"),
                        "cover": ("cover.png", cover, "image/png"),
                    },
                )
            if res.status_code != 200:
                # Don't print full responses: proxy errors could echo headers.
                raise RuntimeError(
                    f"Publishing stopped at {item['slug']}: HTTP {res.status_code}"
                )
            print(
                item["slug"], "published" if res.json()["created"] else "already exists"
            )


if __name__ == "__main__":
    main()
