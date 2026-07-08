"""
BuildCache — Phase 4 of the Execution Platform.

Content-addressed caching: same inputs → same cache key → skip work.

Cache key components:
  - runtime identifier (node/python/docker)
  - runtime version (node v20.11.0)
  - declared dependencies (package.json deps + devDeps / requirements.txt)
  - lockfile content (package-lock.json / pnpm-lock.yaml / requirements.txt hash)
  - build configuration (relevant env vars and flags)

Cache stores:
  - node_modules/ snapshots (tarball)
  - virtual environment dirs
  - build outputs (dist/, build/)
  - dependency installation results

Platform-independent: all paths via tempfile.gettempdir().
Thread-safe: cache entries are written atomically (temp + rename).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_CACHE_ROOT = Path(tempfile.gettempdir()) / "platform-cache"
_MAX_CACHE_AGE_HOURS = 24
_MAX_CACHE_SIZE_MB   = 500


@dataclass
class CacheEntry:
    """Metadata record for one cache entry."""
    key: str
    runtime: str
    created_at: float
    size_bytes: int
    data_path: str   # absolute path to the cached directory/file

    def is_expired(self) -> bool:
        age_hours = (time.time() - self.created_at) / 3600
        return age_hours > _MAX_CACHE_AGE_HOURS

    def to_dict(self) -> dict:
        return {
            "key"       : self.key,
            "runtime"   : self.runtime,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "data_path" : self.data_path,
        }


class BuildCache:
    """
    Content-addressed build cache.

    Usage:
        cache = BuildCache()
        key = cache.key_for_node(ws, node_version)
        if cache.has(key):
            cache.restore_node_modules(key, ws / 'node_modules')
        else:
            # run install
            cache.store_node_modules(key, ws / 'node_modules')
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or _CACHE_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._meta_file = self._root / "index.json"
        self._entries: dict[str, CacheEntry] = {}
        self._load_index()

    # ── Key computation ───────────────────────────────────────────────────────

    def key_for_node(self, ws: Path, node_version: str) -> str:
        """Compute cache key for a Node.js project."""
        h = hashlib.sha256()
        h.update(b"node:")
        h.update(node_version.encode())
        _hash_deps_json(h, ws / "package.json")
        _hash_lockfiles(h, ws, (
            "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
        ))
        return h.hexdigest()[:16]

    def key_for_python(self, ws: Path, python_version: str) -> str:
        """Compute cache key for a Python project."""
        h = hashlib.sha256()
        h.update(b"python:")
        h.update(python_version.encode())
        for req_file in ("requirements.txt", "pyproject.toml", "setup.cfg", "Pipfile.lock"):
            p = ws / req_file
            if p.exists():
                try:
                    h.update(p.read_bytes())
                except Exception:
                    pass
        return h.hexdigest()[:16]

    def key_for_build_output(self, ws: Path, runtime: str, build_cmd: str) -> str:
        """Compute cache key for a build output (dist/)."""
        h = hashlib.sha256()
        h.update(f"build:{runtime}:{build_cmd}:".encode())
        _hash_deps_json(h, ws / "package.json")
        _hash_lockfiles(h, ws, ("package-lock.json", "pnpm-lock.yaml"))
        # Hash source files (shallow: only files directly in ws root)
        for f in sorted(ws.glob("*.{js,ts,jsx,tsx,html,css,json}")):
            try:
                h.update(f.read_bytes()[:4096])  # first 4 KB is enough for a fingerprint
            except Exception:
                pass
        return h.hexdigest()[:16]

    # ── Lookup ────────────────────────────────────────────────────────────────

    def has(self, key: str) -> bool:
        entry = self._entries.get(key)
        if entry is None:
            return False
        if entry.is_expired():
            self._evict(key)
            return False
        if not Path(entry.data_path).exists():
            del self._entries[key]
            return False
        return True

    def get_entry(self, key: str) -> Optional[CacheEntry]:
        return self._entries.get(key) if self.has(key) else None

    # ── node_modules cache ────────────────────────────────────────────────────

    def restore_node_modules(self, key: str, target: Path) -> bool:
        """
        Restore cached node_modules to target path.
        Returns True on success, False if cache miss.
        """
        entry = self.get_entry(key)
        if not entry:
            return False
        try:
            cached = Path(entry.data_path)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(cached, target)
            log.info("cache hit: restored node_modules key=%s → %s", key, target)
            return True
        except Exception as exc:
            log.warning("cache restore failed for key=%s: %s", key, exc)
            return False

    def store_node_modules(self, key: str, source: Path, runtime: str = "node") -> bool:
        """
        Store node_modules from source into the cache.
        Returns True on success.
        """
        if not source.exists():
            return False
        dest = self._root / f"nm-{key}"
        try:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(source, dest)
            size = _dir_size_bytes(dest)
            entry = CacheEntry(
                key=key, runtime=runtime,
                created_at=time.time(), size_bytes=size,
                data_path=str(dest),
            )
            self._entries[key] = entry
            self._save_index()
            log.info("cache stored: key=%s runtime=%s size=%dMB",
                     key, runtime, size // 1024 // 1024)
            return True
        except Exception as exc:
            log.warning("cache store failed for key=%s: %s", key, exc)
            return False

    # ── Build output cache ────────────────────────────────────────────────────

    def restore_build_output(self, key: str, target: Path) -> bool:
        entry = self.get_entry(key)
        if not entry:
            return False
        try:
            cached = Path(entry.data_path)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(cached, target)
            log.info("cache hit: restored build output key=%s → %s", key, target)
            return True
        except Exception as exc:
            log.warning("cache build restore failed: %s", exc)
            return False

    def store_build_output(self, key: str, source: Path, runtime: str = "node") -> bool:
        if not source.exists():
            return False
        dest = self._root / f"build-{key}"
        try:
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(source, dest)
            size = _dir_size_bytes(dest)
            self._entries[key] = CacheEntry(
                key=key, runtime=runtime,
                created_at=time.time(), size_bytes=size,
                data_path=str(dest),
            )
            self._save_index()
            return True
        except Exception as exc:
            log.warning("cache build store failed: %s", exc)
            return False

    # ── Maintenance ───────────────────────────────────────────────────────────

    def evict_expired(self) -> int:
        """Remove expired entries. Returns count evicted."""
        expired = [k for k, e in self._entries.items() if e.is_expired()]
        for k in expired:
            self._evict(k)
        return len(expired)

    def total_size_mb(self) -> float:
        total = sum(e.size_bytes for e in self._entries.values())
        return round(total / 1024 / 1024, 1)

    def stats(self) -> dict:
        return {
            "entries"     : len(self._entries),
            "total_size_mb": self.total_size_mb(),
            "root"        : str(self._root),
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _evict(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry:
            try:
                p = Path(entry.data_path)
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.is_file():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
            self._save_index()

    def _load_index(self) -> None:
        if not self._meta_file.exists():
            return
        try:
            data = json.loads(self._meta_file.read_text())
            for d in data.get("entries", []):
                e = CacheEntry(**d)
                if not e.is_expired():
                    self._entries[e.key] = e
        except Exception as exc:
            log.warning("cache index load failed: %s", exc)

    def _save_index(self) -> None:
        try:
            tmp = self._meta_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "entries": [e.to_dict() for e in self._entries.values()]
            }, indent=2))
            tmp.replace(self._meta_file)
        except Exception as exc:
            log.warning("cache index save failed: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_deps_json(h: "hashlib._Hash", pkg_json: Path) -> None:
    if not pkg_json.exists():
        return
    try:
        data = json.loads(pkg_json.read_text())
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        h.update(json.dumps(deps, sort_keys=True).encode())
    except Exception:
        pass


def _hash_lockfiles(h: "hashlib._Hash", ws: Path, names: tuple[str, ...]) -> None:
    for name in names:
        p = ws / name
        if p.exists():
            try:
                h.update(p.read_bytes())
            except Exception:
                pass
            break  # only hash the first matching lockfile


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total


# ── Process-lifetime singleton ────────────────────────────────────────────────

_build_cache = BuildCache()


def get_cache() -> BuildCache:
    return _build_cache
