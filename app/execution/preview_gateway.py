"""Trusted preview gateway, uploaded into the isolated VM (stdlib only).

The one-time bootstrap URL grants a five-minute, per-sandbox cookie. Platform
credentials never enter this VM. Generated code is served on a separate origin.
"""
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os

TOKEN = os.environ["FLOW_PREVIEW_TOKEN"]
COOKIE = "__Host-flow_preview"
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "upgrade",
               "proxy-authorization", "proxy-authenticate", "te", "trailer"}
MAX_BODY = 10 * 1024 * 1024
UPSTREAM_PORT = 8080


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Never log capability URLs or cookies.

    def _handle(self):
        if self.path == f"/_flow_preview/{TOKEN}" and self.command == "GET":
            self.send_response(303)
            self.send_header("Set-Cookie", f"{COOKIE}={TOKEN}; Path=/; Max-Age=300; "
                             "Secure; HttpOnly; SameSite=None; Partitioned")
            self.send_header("Location", "/")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            value = cookies[COOKIE].value if COOKIE in cookies else ""
        except Exception:
            value = ""
        if not hmac.compare_digest(hashlib.sha256(value.encode()).digest(),
                                   hashlib.sha256(TOKEN.encode()).digest()):
            self.send_error(401, "Preview session required")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if not 0 <= size <= MAX_BODY or self.headers.get("Transfer-Encoding"):
            self.send_error(413)
            return
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_HEADERS | {"cookie", "authorization", "x-sub-token", "x-api-key", "x-organization-id"}}
        # Retain application cookies, never the gateway capability.
        app_cookies = "; ".join(f"{k}={m.coded_value}" for k, m in cookies.items() if k != COOKIE)
        if app_cookies:
            headers["Cookie"] = app_cookies
        connection = http.client.HTTPConnection("127.0.0.1", UPSTREAM_PORT, timeout=15)
        try:
            connection.request(self.command, self.path, self.rfile.read(size), headers)
            response = connection.getresponse()
            body = response.read(MAX_BODY + 1)
            if len(body) > MAX_BODY:
                self.send_error(502, "Preview response too large")
                return
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS | {"content-length", "cache-control", "referrer-policy"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (OSError, http.client.HTTPException):
            self.send_error(502, "Preview application unavailable")
        finally:
            connection.close()

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _handle


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 3000), Gateway).serve_forever()
