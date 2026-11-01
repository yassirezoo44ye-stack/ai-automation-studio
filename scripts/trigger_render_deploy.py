"""Validate the public deploy target before using a secret Render hook."""

from __future__ import annotations

import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class DeployError(Exception):
    """Only non-secret diagnostic text may be included in this exception."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deploy_url(hook: str, service: str, sha: str) -> str:
    if not re.fullmatch(r"srv-[a-z0-9]+", service):
        raise DeployError("RENDER_SERVICE_ID must name the intended Render service.")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
        raise DeployError("GITHUB_SHA must be a full validated commit SHA.")
    if not hook:
        raise DeployError("RENDER_DEPLOY_HOOK_URL is not configured in repository secrets.")
    try:
        url = urlsplit(hook)
        if (url.scheme != "https" or url.hostname != "api.render.com"
                or url.port not in (None, 443) or url.username or url.password or url.fragment):
            raise ValueError
        match = re.fullmatch(r"/deploy/(srv-[a-z0-9]+)", url.path)
        if not match:
            raise ValueError
        actual = match.group(1)
        if actual != service:
            raise DeployError(
                f"Deploy hook targets {actual}, but this workflow must deploy {service}. "
                "Replace RENDER_DEPLOY_HOOK_URL in repository secrets with that service's hook."
            )
        pairs = parse_qsl(url.query, keep_blank_values=True, max_num_fields=10)
        keys = [value for key, value in pairs if key == "key"]
        if len(keys) != 1 or not keys[0] or any(key not in ("key", "ref") for key, _ in pairs):
            raise ValueError
    except ValueError:
        raise DeployError("Deploy hook must be the expected HTTPS Render deploy URL with one key parameter.") from None
    # Replace stale/duplicate refs instead of appending an ambiguous second ref.
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode({"key": keys[0], "ref": sha}), ""))


def trigger(hook: str, service: str, sha: str) -> int:
    target = deploy_url(hook, service, sha)
    try:
        with build_opener(NoRedirects()).open(Request(target, method="POST"), timeout=30) as response:
            status = response.status
    except HTTPError as error:
        status = error.code
        error.close()
    except (URLError, OSError, ValueError):
        # Exception strings can include the secret URL. Never print them.
        raise DeployError("Could not contact Render. Check connectivity and retry; no deploy is confirmed.") from None
    if status not in (200, 201, 202):
        raise DeployError(
            f"Render rejected deployment of {service} with HTTP {status}. "
            "409 means the target service/workspace cannot deploy, not that a deploy started."
        )
    return status


def main() -> int:
    service = os.environ.get("RENDER_SERVICE_ID", "")
    sha = os.environ.get("GITHUB_SHA", "")
    try:
        status = trigger(os.environ.get("RENDER_DEPLOY_HOOK_URL", ""), service, sha)
    except DeployError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1
    print(f"Render accepted {service} at {sha} (HTTP {status}); the health check must verify this exact commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
