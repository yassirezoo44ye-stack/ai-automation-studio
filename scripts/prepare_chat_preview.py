"""Generate a separate Vercel preview config; never alter production config."""
import argparse
import copy
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

_STAGING_NAME = "flow-chat-review-api"


def _staging_origin(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    allowed = re.fullmatch(
        rf"{_STAGING_NAME}(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?\.onrender\.com", host
    ) is not None
    if (
        parsed.scheme != "https" or not allowed or parsed.username or parsed.password
        or parsed.port not in (None, 443) or parsed.path not in ("", "/")
        or parsed.query or parsed.fragment
    ):
        raise ValueError("Use the approved flow-chat-review-api HTTPS origin only.")
    return f"https://{host}"


def make_preview_config(source: dict, backend_url: str) -> dict:
    origin = _staging_origin(backend_url)
    result = copy.deepcopy(source)
    rules = [r for r in result.get("rewrites", []) if r.get("source") == "/api/:path*"]
    if len(rules) != 1:
        raise ValueError("Expected exactly one existing API rewrite.")
    old_host = urlsplit(rules[0].get("destination", "")).hostname
    if not old_host:
        raise ValueError("Existing API destination must have an explicit hostname.")
    rules[0]["destination"] = f"{origin}/api/:path*"
    updated = 0
    for block in result.get("headers", []):
        for header in block.get("headers", []):
            if header.get("key", "").lower() != "content-security-policy":
                continue
            directives = [part.strip() for part in header["value"].split(";") if part.strip()]
            if sum(part.split()[0].lower() == "connect-src" for part in directives) != 1:
                raise ValueError("Each CSP must contain exactly one connect-src directive.")
            for index, directive in enumerate(directives):
                parts = directive.split()
                if parts and parts[0].lower() == "connect-src":
                    kept = [token for token in parts[1:] if urlsplit(token).hostname != old_host]
                    for token in (origin, origin.replace("https://", "wss://", 1)):
                        if token not in kept:
                            kept.append(token)
                    directives[index] = "connect-src " + " ".join(kept)
                    updated += 1
            header["value"] = "; ".join(directives) + ";"
    if not updated:
        raise ValueError("Expected an existing CSP connect-src directive.")
    return result


def write_preview_config(source_path: Path, output_path: Path, backend_url: str) -> None:
    if source_path.resolve() == output_path.resolve() or (
        output_path.exists() and source_path.samefile(output_path)
    ):
        raise ValueError("Output must be separate from the production source config.")
    config = make_preview_config(
        json.loads(source_path.read_text(encoding="utf-8")), backend_url
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_path.parent,
            prefix=".flow-preview-", suffix=".json", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="vercel.json")
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        write_preview_config(Path(args.source), Path(args.output), args.backend_url)
    except (OSError, ValueError):
        parser.error("Could not generate preview config. Check the separate output path, source JSON and approved staging origin.")


if __name__ == "__main__":
    main()

