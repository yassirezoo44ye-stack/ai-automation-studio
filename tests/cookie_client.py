"""Send one request with extra cookies, without per-request ``cookies=``.

httpx (and Starlette's TestClient, which wraps it) deprecated passing
``cookies=`` to individual request calls because it is ambiguous whether
those cookies should persist on the client. The supported way is to set
cookies on the client instance. This helper does exactly that, scoped to
a single request: the given cookies are set on the client, the request is
sent, and the injected names are removed again so later requests in the
same test (or a shared client fixture) behave as they did before.
"""
from __future__ import annotations

from typing import Any


def request_with_cookies(client: Any, method: str, url: str, *,
                         cookies: dict[str, str], **kwargs: Any) -> Any:
    for name, value in cookies.items():
        client.cookies.set(name, value)
    try:
        return client.request(method, url, **kwargs)
    finally:
        for name in cookies:
            client.cookies.delete(name)
