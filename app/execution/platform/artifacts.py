"""
ArtifactSystem — Phase 5 of the Execution Platform.

Versioned, timestamped artifact storage for every execution.

Artifact kinds:
  log       — stdout/stderr capture from a phase
  dist      — built output (dist/, build/, .next/static)
  report    — JSON execution report
  screenshot — PNG screenshot of a running server

Each artifact has:
  - A unique ID (UUID)
  - Kind, name, MIME type
  - Size in bytes
  - Creation timestamp
  - Absolute path on disk

Artifacts are stored under $TMPDIR/platform-artifacts/{execution_id}/
and are retrievable via the Runtime API until the execution is cleaned up.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import uuid4

log = logging.getLogger(__name__)

_ARTIFACT_ROOT = Path(tempfile.gettempdir()) / "platform-artifacts"

_KIND_MIME = {
    "log"       : "text/plain",
    "dist"      : "application/zip",
    "report"    : "application/json",
    "screenshot": "image/png",
    "archive"   : "application/zip",
}


@dataclass
class Artifact:
    """A single collected artifact."""
    id: str
    execution_id: str
    kind: str                # "log" | "dist" | "report" | "screenshot"
    name: str                # human-readable filename
    path: str                # absolute path to the file on disk
    size_bytes: int
    created_at: float
    mime_type: str

    @property
    def exists(self) -> bool:
        return Path(self.path).exists()

    def to_dict(self) -> dict:
        return {
            "id"          : self.id,
            "execution_id": self.execution_id,
            "kind"        : self.kind,
            "name"        : self.name,
            "path"        : self.path,
            "size_bytes"  : self.size_bytes,
            "created_at"  : round(self.created_at, 3),
            "mime_type"   : self.mime_type,
            "exists"      : self.exists,
        }


class ArtifactSystem:
    """
    Manages artifacts for one execution.

    Usage:
        arts = ArtifactSystem(execution_id)
        arts.init()
        # during execution:
        artifact = arts.add_file("log", "install.log", log_path)
        artifact = arts.add_bytes("report", "report.json", json_bytes)
        # after:
        for a in arts.all():
            print(a.name, a.size_bytes)
        arts.cleanup()
    """

    def __init__(self, execution_id: str, root: Optional[Path] = None) -> None:
        self.execution_id = execution_id
        self._root = (root or _ARTIFACT_ROOT) / execution_id
        self._artifacts: dict[str, Artifact] = {}
        self._initialized = False

    def init(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._initialized = True

    # ── Adding artifacts ──────────────────────────────────────────────────────

    def add_file(self, kind: str, name: str, source: Path) -> Optional[Artifact]:
        """
        Copy source file into the artifact store.
        Returns the Artifact on success, None on failure.
        """
        self._ensure_init()
        if not source.exists():
            log.warning("artifact add_file: source does not exist: %s", source)
            return None
        try:
            art_id  = str(uuid4())[:8]
            dest    = self._root / f"{art_id}-{name}"
            shutil.copy2(source, dest)
            size    = dest.stat().st_size
            art     = self._make(art_id, kind, name, str(dest), size)
            self._artifacts[art_id] = art
            log.info("artifact collected: kind=%s name=%s size=%d", kind, name, size)
            return art
        except Exception as exc:
            log.warning("artifact add_file failed: %s", exc)
            return None

    def add_bytes(self, kind: str, name: str, data: bytes) -> Optional[Artifact]:
        """Write raw bytes into the artifact store."""
        self._ensure_init()
        try:
            art_id  = str(uuid4())[:8]
            dest    = self._root / f"{art_id}-{name}"
            dest.write_bytes(data)
            art     = self._make(art_id, kind, name, str(dest), len(data))
            self._artifacts[art_id] = art
            return art
        except Exception as exc:
            log.warning("artifact add_bytes failed: %s", exc)
            return None

    def add_text(self, kind: str, name: str, text: str) -> Optional[Artifact]:
        return self.add_bytes(kind, name, text.encode("utf-8", errors="replace"))

    def add_directory(self, kind: str, name: str, source: Path) -> Optional[Artifact]:
        """
        Zip a directory and store the archive as an artifact.
        Returns the Artifact, or None on failure.
        """
        self._ensure_init()
        if not source.is_dir():
            return None
        try:
            art_id   = str(uuid4())[:8]
            zip_name = name if name.endswith(".zip") else name + ".zip"
            dest     = self._root / f"{art_id}-{zip_name}"
            archive  = shutil.make_archive(str(dest.with_suffix("")), "zip", source)
            dest     = Path(archive)
            size     = dest.stat().st_size
            art      = self._make(art_id, "archive", zip_name, str(dest), size)
            self._artifacts[art_id] = art
            log.info("artifact directory archived: name=%s size=%d", zip_name, size)
            return art
        except Exception as exc:
            log.warning("artifact add_directory failed: %s", exc)
            return None

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, artifact_id: str) -> Optional[Artifact]:
        return self._artifacts.get(artifact_id)

    def all(self) -> list[Artifact]:
        return list(self._artifacts.values())

    def by_kind(self, kind: str) -> list[Artifact]:
        return [a for a in self._artifacts.values() if a.kind == kind]

    def count(self) -> int:
        return len(self._artifacts)

    def total_size_bytes(self) -> int:
        return sum(a.size_bytes for a in self._artifacts.values())

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_index(self) -> None:
        """Write artifact index to disk for later retrieval."""
        try:
            index = {
                "execution_id": self.execution_id,
                "saved_at"    : round(time.time(), 3),
                "artifacts"   : [a.to_dict() for a in self._artifacts.values()],
            }
            (self._root / "index.json").write_text(json.dumps(index, indent=2))
        except Exception as exc:
            log.warning("artifact index save failed: %s", exc)

    @classmethod
    def load(cls, execution_id: str, root: Optional[Path] = None) -> "ArtifactSystem":
        """Load an existing artifact collection from disk."""
        system = cls(execution_id, root)
        system._root.mkdir(parents=True, exist_ok=True)
        system._initialized = True
        index_path = system._root / "index.json"
        if not index_path.exists():
            return system
        try:
            data = json.loads(index_path.read_text())
            for d in data.get("artifacts", []):
                try:
                    art = Artifact(
                        id          =d["id"],
                        execution_id=d["execution_id"],
                        kind        =d["kind"],
                        name        =d["name"],
                        path        =d["path"],
                        size_bytes  =d["size_bytes"],
                        created_at  =d["created_at"],
                        mime_type   =d.get("mime_type", "application/octet-stream"),
                    )
                    system._artifacts[art.id] = art
                except KeyError as ke:
                    log.warning("artifact load skipped entry (missing key %s)", ke)
        except Exception as exc:
            log.warning("artifact load failed: %s", exc)
        return system

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self) -> int:
        """Remove all stored artifacts. Returns bytes freed."""
        freed = 0
        for a in self._artifacts.values():
            try:
                p = Path(a.path)
                if p.exists():
                    freed += p.stat().st_size
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            shutil.rmtree(self._root, ignore_errors=True)
        except Exception:
            pass
        self._artifacts.clear()
        return freed

    # ── Internal ─────────────────────────────────────────────────────────────

    def _ensure_init(self) -> None:
        if not self._initialized:
            self.init()

    def _make(self, art_id: str, kind: str, name: str, path: str, size: int) -> Artifact:
        mime = _KIND_MIME.get(kind) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return Artifact(
            id          =art_id,
            execution_id=self.execution_id,
            kind        =kind,
            name        =name,
            path        =path,
            size_bytes  =size,
            created_at  =time.time(),
            mime_type   =mime,
        )
