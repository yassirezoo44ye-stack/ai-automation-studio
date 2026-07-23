"""
Rate limiting and per-request cost-protection guards.

Superseded by app/core/rate_limit.py: that module fixed a rate-limit
bypass this one had (keying on the client-spoofable LEFTMOST
X-Forwarded-For entry instead of the trusted rightmost one appended by the
nearest proxy — an attacker could get a fresh bucket on every request just
by varying a fake leftmost IP, see rate_limit.py's _real_ip() docstring),
and added Redis backing so limits hold across multiple app instances
instead of each process keeping its own independent in-memory counter.

This module now re-exports that implementation so every existing call
site (check_rate_limit, ai_rate_limit — build.py, chat.py, design.py,
agents.py, social.py, youtube.py) gets the fix and the Redis backing
automatically, with zero call-site changes.
"""
from app.core.rate_limit import ai_rate_limit, check_rate_limit

__all__ = ["ai_rate_limit", "check_rate_limit"]
